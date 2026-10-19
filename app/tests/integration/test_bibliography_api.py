"""Exercise opt-in enrichment through actual metadata and import endpoints."""
import copy
import json
import time

import fitz
from pydantic import SecretStr
import pytest
import requests

from dlrag.ingestion.metadata_api import recognize_metadata

TITLE = "Evidence Search: Reliable Metadata for Libraries"
AUTHORS = ["Alice Smith", "Bob Jones"]


def fixture_pdf(*, publication=True):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 70), TITLE, fontsize=13)
        page.insert_text((40, 110), "Alice Smith and Bob Jones")
        if publication:
            page.insert_text((40, 150), "Proceedings of the Library Conference")
            page.insert_text((40, 180), "doi:10.1234/library.1")
        return pdf.tobytes()


def setup(services, monkeypatch):
    services.settings.app_mode = "real"
    services.settings.siliconflow_api_key = SecretStr("synthetic-model-key")
    reply = {"title": {"value": TITLE, "pdf_page": 1, "excerpt": TITLE},
             "authors": {"value": AUTHORS, "pdf_page": 1, "excerpt": "Alice Smith and Bob Jones"}}
    monkeypatch.setattr("dlrag.ingestion.metadata_api.request_candidates", lambda *args: copy.deepcopy(reply))


def wait(client, job_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = client.get("/document-jobs/" + job_id).json()
        if job["stage"] in {"done", "error"}:
            return job
        time.sleep(.01)
    pytest.fail("metadata job timeout")


@pytest.mark.parametrize("as_job", [True, False])
def test_opt_in_fills_with_provenance_without_import_until_confirmed(client, services, monkeypatch, as_job):
    setup(services, monkeypatch)
    row = {"title": [TITLE], "author": [{"given": "Alice", "family": "Smith"}, {"given": "Bob", "family": "Jones"}],
           "DOI": "10.1234/library.1", "type": "proceedings-article", "published-print": {"date-parts": [[2024]]}}
    monkeypatch.setattr("dlrag.ingestion.bibliography.query_crossref", lambda *args: [row])
    data = fixture_pdf()
    response = client.post("/documents/metadata" + ("/jobs" if as_job else ""),
                           files={"file": ("fixture.pdf", data, "application/pdf")}, data={"use_lookup": "true"})
    if as_job:
        job = wait(client, response.json()["job_id"])
        assert "bibliographic_lookup" in job["stages"]
        result = job["result"]
    else:
        assert response.status_code == 200
        result = response.json()
    assert result["metadata"]["year"] == 2024
    assert result["metadata"]["source_url"] == "https://doi.org/10.1234/library.1"
    assert result["field_sources"]["year"]["method"] == "bibliographic_lookup"
    assert result["requires_confirmation"]
    assert services.library.list_documents(include_nonready=True) == [] and services.manifest() is None
    result["metadata"]["topics"] = ["自然科学"]  # User selects a discipline after preview.
    response = client.post("/documents/jobs", files={"file": ("fixture.pdf", data, "application/pdf")},
                           data={"metadata_json": json.dumps(result["metadata"])})
    imported = wait(client, response.json()["job_id"])
    assert imported["stage"] == "done" and imported["result"]["document"]["year"] == 2024


@pytest.mark.parametrize("gate", ["not_requested", "server_disabled", "assist_off", "mock", "no_key", "model_failed"])
def test_no_external_query_without_opt_in_and_successful_enhancement(services, monkeypatch, tmp_path, gate):
    setup(services, monkeypatch)
    def unexpected(*args):
        pytest.fail("external query should be skipped")
    monkeypatch.setattr("dlrag.ingestion.bibliography.query_crossref", unexpected)
    if gate == "server_disabled":
        services.settings.metadata_lookup_enabled = False
    elif gate == "mock":
        services.settings.app_mode = "mock"
    elif gate == "no_key":
        services.settings.siliconflow_api_key = SecretStr("")
    elif gate == "model_failed":
        def broken(*args):
            raise requests.Timeout("model-private-key")
        monkeypatch.setattr("dlrag.ingestion.metadata_api.request_candidates", broken)
    path = tmp_path / "fixture.pdf"
    path.write_bytes(fixture_pdf())
    result = recognize_metadata(path, services.settings, lookup=gate != "not_requested", assist=gate != "assist_off")
    assert result["bibliographic_enrichment"]["status"] in {"not_requested", "disabled", "skipped"}
    assert "model-private-key" not in str(result)


def test_lookup_outage_does_not_turn_successful_model_preview_into_error(client, services, monkeypatch):
    setup(services, monkeypatch)
    def offline(*args):
        raise requests.ConnectionError("private-server-body")
    monkeypatch.setattr("dlrag.ingestion.bibliography.query_crossref", offline)
    response = client.post("/documents/metadata/jobs", files={"file": ("fixture.pdf", fixture_pdf(), "application/pdf")},
                           data={"use_lookup": "true"})
    job = wait(client, response.json()["job_id"])
    assert job["stage"] == "done"
    assert job["result"]["api_assistance"]["status"] == "completed"
    assert job["result"]["metadata"]["authors"] == AUTHORS
    assert job["result"]["bibliographic_enrichment"]["error_code"] == "UNAVAILABLE"
    assert "private-server-body" not in str(job)
    assert services.library.list_documents(include_nonready=True) == []


def test_ui_lookup_opt_in_and_external_evidence_render(client, imported, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    from streamlit.testing.v1 import AppTest

    seen = []
    def recognized(*args, **kwargs):
        seen.append(kwargs.get("lookup", False))
        result = {"metadata": {"title": TITLE, "authors": AUTHORS, "year": None, "source_url": None},
                  "field_sources": {}, "warnings": [], "bibliographic_enrichment": {"status": "not_requested"}}
        if kwargs.get("lookup"):
            result["metadata"]["year"] = 2024
            result["field_sources"]["year"] = {"method": "bibliographic_lookup", "provider": "crossref",
                "record_url": "https://api.crossref.org/works/10.1234%2Flibrary.1", "excerpt": "published-print: 2024",
                "date_type": "published-print"}
        return result
    monkeypatch.setattr("dlrag.ingestion.metadata_api.recognize_metadata", recognized)
    monkeypatch.setattr("dlrag.ui.client.call_api", lambda base, method, path, **kwargs:
                        client.request(method, path, **kwargs).json())
    monkeypatch.setattr("streamlit.file_uploader", lambda *a, **k:
                        SimpleNamespace(name="fixture.pdf", getvalue=fixture_pdf))
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"), default_timeout=20).run()
    app.sidebar.radio[0].set_value("上传与管理").run()
    assert not app.exception and seen == [False]
    next(w for w in app.toggle if w.label == "联网补全出版资料").set_value(True).run()
    next(w for w in app.button if w.label == "重新识别文献信息").click().run()
    assert not app.exception and seen[-1] is True
    assert app.text_input(key="upload_year").value == "2024"
    assert any("外部出版记录" in w.value for w in app.markdown)
    assert any("published-print: 2024" in c.value for c in app.caption)
    assert app.text_input(key="upload_year").label == "版本年份（可留空）"
    assert any("日期依据：印刷出版日期" in c.value for c in app.caption)


@pytest.mark.parametrize("stamp,expected", [("", None), ("arXiv:2111.13824v4 17 Feb 2023", 2023)])
def test_lookup_cannot_replace_a_manuscript_version_with_the_formal_year(client, services, monkeypatch, stamp, expected):
    setup(services, monkeypatch)
    if stamp:
        reply = {"title": {"value": TITLE, "pdf_page": 1, "excerpt": TITLE},
                 "year": {"value": 2023, "pdf_page": 1, "excerpt": stamp, "date_type": "version"}}
        monkeypatch.setattr("dlrag.ingestion.metadata_api.request_candidates", lambda *args: reply)
    with fitz.open(stream=fixture_pdf(publication=False), filetype="pdf") as pdf:
        if stamp:
            pdf[0].insert_text((40, 150), stamp)
        data = pdf.tobytes()
    row = {"title": [TITLE], "author": [{"given": "Alice", "family": "Smith"}, {"given": "Bob", "family": "Jones"}],
           "DOI": "10.1234/library.1", "type": "journal-article", "published-print": {"date-parts": [[2024]]}}
    monkeypatch.setattr("dlrag.ingestion.bibliography.query_crossref", lambda *args: [row])
    result = client.post("/documents/metadata", files={"file": ("fixture.pdf", data, "application/pdf")},
                         data={"use_lookup": "true"}).json()
    assert result["metadata"]["year"] == expected
    if stamp:
        assert result["bibliographic_enrichment"]["status"] == "not_needed"
    else:
        assert result["bibliographic_enrichment"]["year_decision"] == "version_not_confirmed"
