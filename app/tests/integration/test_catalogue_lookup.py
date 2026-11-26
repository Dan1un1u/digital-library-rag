"""Reader workflows for full-text results and title/author lookup."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from dlrag.api.main import create_app
from dlrag.shared.config import Settings
from scripts.seed_demo import create_pdf


@pytest.fixture
def catalogue(tmp_path):
    settings = Settings(app_mode="mock", data_dir=tmp_path / "catalogue", _env_file=None)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        rows = [
            ("Catalogue Discovery", "Mélanie Li", 2024, ["自然科学", "Cataloguing"]),
            ("Catalogue Discovery Methods", "其他作者", 2025, ["自然科学"]),
            ("Research Methods", "Catalogue Discovery", 2023, ["社会科学"]),
        ]
        for number, (title, author, year, topics) in enumerate(rows):
            path = tmp_path / f"{number}.pdf"
            create_pdf(path, [f"Study {number}. This passage introduces bibliographic discovery methods."])
            response = client.post("/documents", files={"file": (path.name, path.read_bytes(), "application/pdf")},
                                   data={"metadata_json": json.dumps(dict(title=title, authors=[author], year=year, topics=topics))})
            assert response.status_code == 200
        yield client


def test_full_text_result_contains_topics_from_the_hit(catalogue):
    result = catalogue.post("/search", json={"query": "bibliographic discovery", "mode": "keyword"}).json()
    for item in result["documents"]:
        detail = catalogue.get(f"/documents/{item['doc_id']}").json()["document"]
        assert item["topics"] == detail["topics"]


def test_exact_title_then_exact_author_then_prefix(catalogue):
    result = catalogue.get("/documents", params={"catalogue_query": "  ＣＡＴＡＬＯＧＵＥ   discovery "})
    assert [d["title"] for d in result.json()["documents"]] == [
        "Catalogue Discovery", "Research Methods", "Catalogue Discovery Methods"
    ]


@pytest.mark.parametrize(("term", "expected"), [("MÉLANIE LI", ["Catalogue Discovery"]),
                                                  ("其他作者", ["Catalogue Discovery Methods"]),
                                                  ("no matching author or title", [])])
def test_author_and_no_results(catalogue, term, expected):
    result = catalogue.get("/documents", params={"catalogue_query": term})
    assert [d["title"] for d in result.json()["documents"]] == expected


def test_catalogue_query_composes_with_existing_filters(catalogue):
    result = catalogue.get("/documents", params={
        "catalogue_query": "catalogue discovery", "year_from": 2024, "topics": ["自然科学"]
    })
    assert [d["title"] for d in result.json()["documents"]] == [
        "Catalogue Discovery", "Catalogue Discovery Methods"
    ]
    assert catalogue.get("/documents", params={"catalogue_query": "   "}).status_code == 422
    assert len(catalogue.get("/documents").json()["documents"]) == 3


def test_bilingual_lookup_in_existing_search_page(catalogue, monkeypatch):
    def call_api(base, method, path, **kwargs):
        response = catalogue.request(method, path, **kwargs)
        return {"_failure": response.json()["error"]} if response.is_error else response.json()

    monkeypatch.setattr("dlrag.ui.client.call_api", call_api)
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"))
    app.query_params["lang"] = "en"
    app.run()
    app.sidebar.radio[0].set_value("搜索与问答").run()
    assert "Find by title or author" in app.radio(key="query_action").options
    app.radio(key="query_action").set_value("题名或作者")
    app.text_area(key="query_question").set_value("Mélanie Li")
    app.button(key="FormSubmitter:query-Submit").click().run()
    assert not app.exception
    assert any("Catalogue Discovery" in item.value for item in app.markdown)
    assert any(item.value == "Documents shown: 1" for item in app.caption)
