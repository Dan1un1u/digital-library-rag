from pathlib import Path

import fitz
from streamlit.testing.v1 import AppTest

from dlrag.ui.library import DOMAINS, cover_card, discipline, domain_counts


def test_discipline_is_exclusive_and_explicit_tags_win():
    docs = [{"title": "Language models and retrieval"},
            {"title": "Language models", "topics": ["社会科学"]},
            {"title": "History of arts"}, {"title": "Unknown"},
            {"title": "Language models in education"}]
    assert domain_counts(docs) == ({"自然科学": 1, "社会科学": 1, "哲学与人文科学": 1}, 2)
    assert discipline({"topics": list(DOMAINS)}) is None


def test_cover_card_escapes_metadata_and_links_pdf():
    html = cover_card({"doc_id": "id/one", "title": '<script>alert("x")</script>', "authors": ["<b>name</b>"]}, "http://localhost:8000")
    assert "<script>" not in html and "<b>name" not in html
    assert "/documents/id%2Fone/cover" in html
    assert "/documents/id%2Fone/file" in html


def test_pdf_cover_is_bounded_cached_and_read_only(client, imported, services):
    doc_id = imported["document"]["doc_id"]
    path = services.file_path(doc_id)
    before = path.read_bytes()
    response = client.get(f"/documents/{doc_id}/cover")
    assert response.status_code == 200 and response.headers["content-type"] == "image/png"
    image = fitz.Pixmap(response.content)
    assert max(image.width, image.height) <= 641
    assert client.get(f"/documents/{doc_id}/cover").content == response.content
    assert path.read_bytes() == before
    assert client.get("/documents/missing/cover").status_code == 404


def test_navigation_and_secondary_settings(client, imported, monkeypatch):
    monkeypatch.setattr("dlrag.ui.client.call_api", lambda base, method, path, **kwargs: client.request(method, path, **kwargs).json())
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"), default_timeout=20).run()
    assert not app.exception
    assert app.sidebar.radio[0].options == ["馆藏展示", "搜索与问答", "上传与管理"]
    assert [m.label for m in app.metric] == ["馆藏文献", *DOMAINS]
    app.sidebar.radio[1].set_value("热门电子文献资源").run()
    assert any("book-card" in m.value and "/cover" in m.value for m in app.markdown)
    app.sidebar.radio[0].set_value("上传与管理").run()
    assert not app.exception
    assert any(b.label == "导入文献" for b in app.button)
    assert not any("索引" in m.value or "总体评估" in m.value for m in app.markdown)
    assert not any("MOCK" in w.value for w in app.warning)
    app.sidebar.radio[1].set_value("系统设置").run()
    assert not app.exception
    assert any("MOCK" in w.value for w in app.warning)
    assert any(e.label == "模式切换说明" for e in app.expander)
