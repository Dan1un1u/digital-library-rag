"""The recovery entry point preserves the source and admits only the repaired PDF."""
import hashlib
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import fitz
import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from dlrag.api.main import create_app
from dlrag.retrieval.errors import ProjectError
from test_fulltext_gate import mixed_pdf, wait_job
from test_text_quality_gate import encoded_pdf


def doc_id(path):
    return "d_" + hashlib.sha256(path.read_bytes()).hexdigest()


def upload(client, path, raw_fields=None):
    fields = {"title": "Recovery sample", "authors": ["Catalogue Author"], "year": 2024,
              "topics": ["自然科学", "Review topic"]}
    fields.update(raw_fields or {})
    return client.post("/documents", files={"file": (path.name, path.read_bytes(), "application/pdf")},
                       data={"metadata_json": json.dumps(fields)})


def cases(client):
    result = client.get("/document-recoveries")
    assert result.status_code == 200, result.text
    return result.json()["cases"]


def replace_job(client, original, path, fields=None):
    result = client.post(f"/documents/{original}/recovery/jobs",
                         files={"file": (path.name, path.read_bytes(), "application/pdf")},
                         data={"metadata_json": json.dumps(fields or {})})
    assert result.status_code == 202, result.text
    return wait_job(client, result.json()["job_id"])


@pytest.mark.parametrize("kind, code, page, query", [
    ("scan", "FULLTEXT_REVIEW_REQUIRED", 2, "Scanned body evidence"),
    ("encoding", "TEXT_LAYER_REVIEW_REQUIRED", 1, "Synthetic body for text quality"),
])
def test_blocked_pdf_recovery_is_linked_and_searchable_after_restart(client, services, imported, tmp_path,
                                                                     kind, code, page, query):
    if kind == "scan":
        raw = mixed_pdf(tmp_path / "original.pdf")
        repaired = mixed_pdf(tmp_path / "repaired.pdf", mode="ocr")
    else:
        raw = encoded_pdf(tmp_path / "original.pdf")
        repaired = encoded_pdf(tmp_path / "repaired.pdf", broken=False)
    original_id, replacement_id = doc_id(raw), doc_id(repaired)
    blocked = upload(client, raw)
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == code
    [case] = cases(client)
    assert case["original"]["doc_id"] == original_id
    assert case["suspect_pages"] == [page] and case["attempts"] == []
    assert case["status"] == "pending"
    assert client.get(f"/documents/{original_id}/file").content == raw.read_bytes()

    job = replace_job(client, original_id, repaired, {"year": None})
    assert job["stage"] == "done", job
    candidate = job["result"]["document"]
    assert candidate["doc_id"] == replacement_id and candidate["status"] == "ready"
    assert candidate["year"] is None and candidate["authors"] == ["Catalogue Author"]
    [case] = cases(client)
    assert case["status"] == "recovered"
    assert case["original"]["status"] == "failed"
    assert case["suspect_pages"] == [page]
    assert [x["document"]["doc_id"] for x in case["attempts"]] == [replacement_id]
    assert case["attempts"][0]["document"]["status"] == "ready"
    assert client.get(f"/documents/{original_id}/file").content == raw.read_bytes()
    assert client.get(f"/documents/{replacement_id}/file").content == repaired.read_bytes()

    replay = replace_job(client, original_id, repaired)
    assert replay["stage"] == "done"
    assert replay["result"]["index_version"] == job["result"]["index_version"]
    assert len(cases(client)[0]["attempts"]) == 1
    with TestClient(create_app(services.settings)) as restarted:
        assert cases(restarted)[0]["status"] == "recovered"
        ready = {doc["doc_id"] for doc in restarted.get("/documents").json()["documents"]}
        assert replacement_id in ready and original_id not in ready
        for mode in ("keyword", "vector", "hybrid"):
            result = restarted.post("/search", json={"query": query, "mode": mode})
            assert result.status_code == 200
            assert any(row["doc_id"] == replacement_id for row in result.json()["documents"])



def test_fully_scanned_document_keeps_detected_page(client, tmp_path):
    mixed = mixed_pdf(tmp_path / "mixed.pdf")
    path = tmp_path / "scan-only.pdf"
    with fitz.open(mixed) as document:
        document.delete_page(0)
        document.save(path)
    blocked = upload(client, path)
    assert blocked.status_code == 422
    assert blocked.json()["error"]["code"] == "NO_EXTRACTABLE_TEXT"
    [case] = cases(client)
    assert case["original"]["doc_id"] == doc_id(path)
    assert case["suspect_pages"] == [1]
    assert client.get(f"/documents/{doc_id(path)}/file").content == path.read_bytes()


def test_failed_and_duplicate_attempts_do_not_add_searchable_documents(client, services, imported, pdf, tmp_path):
    raw = mixed_pdf(tmp_path / "original.pdf")
    bad = encoded_pdf(tmp_path / "still-broken.pdf")
    repaired = mixed_pdf(tmp_path / "corrected.pdf", mode="ocr")
    second_raw = mixed_pdf(tmp_path / "other-original.pdf", rotation=90)
    alternate = mixed_pdf(tmp_path / "alternate.pdf", mode="ocr", rotation=90)
    original_id, bad_id = doc_id(raw), doc_id(bad)
    assert upload(client, raw).status_code == 422
    assert upload(client, second_raw).status_code == 422
    before = services.manifest()

    assert replace_job(client, original_id, raw)["error"]["code"] == "REPLACEMENT_UNCHANGED"
    assert replace_job(client, original_id, pdf)["error"]["code"] == "REPLACEMENT_ALREADY_STORED"
    assert replace_job(client, doc_id(pdf), repaired)["error"]["code"] == "RECOVERY_NOT_AVAILABLE"
    error = replace_job(client, original_id, bad)["error"]
    assert error["code"] == "TEXT_LAYER_REVIEW_REQUIRED"
    assert error["fulltext_review"]["suspect_pages"] == [1]
    assert replace_job(client, original_id, bad)["error"]["code"] == "TEXT_LAYER_REVIEW_REQUIRED"
    assert replace_job(client, bad_id, repaired)["error"]["code"] == "RECOVERY_NOT_AVAILABLE"
    assert services.manifest() == before
    assert {doc["doc_id"] for doc in client.get("/documents").json()["documents"]} == {doc_id(pdf)}

    by_original = {case["original"]["doc_id"]: case for case in cases(client)}
    assert set(by_original) == {original_id, doc_id(second_raw)}
    attempt, = by_original[original_id]["attempts"]
    assert attempt["document"]["doc_id"] == bad_id and attempt["document"]["status"] == "failed"
    assert attempt["suspect_pages"] == [1]
    assert client.get(f"/documents/{bad_id}/file").content == bad.read_bytes()

    assert replace_job(client, original_id, repaired)["result"]["document"]["status"] == "ready"
    assert replace_job(client, original_id, alternate)["error"]["code"] == "RECOVERY_ALREADY_RESOLVED"
    assert replace_job(client, doc_id(second_raw), repaired)["error"]["code"] == "REPLACEMENT_ALREADY_STORED"
    assert services.library.get_document(doc_id(alternate)) is None
    by_original = {case["original"]["doc_id"]: case for case in cases(client)}
    assert [entry["document"]["status"] for entry in by_original[original_id]["attempts"]] == ["failed", "ready"]
    assert by_original[doc_id(second_raw)]["attempts"] == []


def test_replacement_index_retry_reuses_saved_text(client, services, imported, tmp_path, monkeypatch):
    raw = mixed_pdf(tmp_path / "failed.pdf")
    repaired = mixed_pdf(tmp_path / "fixed.pdf", mode="ocr")
    alternate = mixed_pdf(tmp_path / "fixed2.pdf", mode="ocr")
    assert upload(client, raw).status_code == 422
    old_manifest = services.manifest()
    original_id = doc_id(raw)
    with monkeypatch.context() as patch:
        patch.setattr(services.retriever.backend, "encode",
                      Mock(side_effect=ProjectError("EMBEDDING_UNAVAILABLE", "injected outage")))
        job = replace_job(client, original_id, repaired)
        assert job["error"]["code"] == "EMBEDDING_UNAVAILABLE"
        [case] = cases(client)
        assert case["status"] == "pending" and case["attempts"][0]["document"]["status"] == "indexing"
        assert services.manifest() == old_manifest
        assert replace_job(client, original_id, alternate)["error"]["code"] == "RECOVERY_IN_PROGRESS"
        assert client.get(f"/documents/{original_id}/file").content == raw.read_bytes()

    parse = Mock(side_effect=AssertionError("the already stored body should not be parsed again"))
    monkeypatch.setattr(services.library, "_parse_document", parse)
    job = replace_job(client, original_id, repaired)
    assert job["stage"] == "done" and job["result"]["index_version"] != old_manifest["index_version"]
    assert cases(client)[0]["status"] == "recovered" and len(cases(client)[0]["attempts"]) == 1
    parse.assert_not_called()


def test_version_two_library_migrates_and_exposes_old_page_references(client, services, imported, tmp_path):
    seed = mixed_pdf(tmp_path / "mixed.pdf")
    raw = tmp_path / "legacy.pdf"
    with fitz.open(seed) as document:
        document.fullcopy_page(1)
        document.new_page().insert_text((45, 100), "Supplementary machine-readable text.")
        document.fullcopy_page(1)
        document.save(raw)
    assert upload(client, raw).status_code == 422
    original_id = doc_id(raw)
    original = services.library.get_document(original_id)
    ready = imported["document"]
    chunks = services.library.list_chunks()
    with sqlite3.connect(services.settings.db_path) as db:
        db.execute("DROP TABLE document_fulltext_reviews")
        db.execute("DROP TABLE document_replacements")
        db.execute("PRAGMA user_version=2")

    with TestClient(create_app(services.settings)) as upgraded:
        [case] = cases(upgraded)
        assert case["original"]["file_sha256"] == original["file_sha256"]
        assert case["suspect_pages"] == [2, 3, 5]
        assert upgraded.get(f"/documents/{ready['doc_id']}").json()["document"] == ready
        assert upgraded.get(f"/documents/{original_id}/file").content == raw.read_bytes()
        assert upgraded.app.state.services.library.list_chunks() == chunks
        assert upgraded.app.state.services.manifest()["index_version"] == imported["index_version"]
        with sqlite3.connect(services.settings.db_path) as db:
            assert db.execute("PRAGMA user_version").fetchone() == (3,)
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("language, panel, action, success", [
    ("zh", "入库失败恢复", "提交修正版并重新验证", "修正版已入库，可在馆藏中检索。"),
    ("en", "Failed import recovery", "Submit and revalidate replacement",
     "The replacement was added and can now be found in search."),
])
def test_management_ui_can_review_page_and_submit(client, tmp_path, monkeypatch, language, panel, action, success):
    raw = mixed_pdf(tmp_path / "scan.pdf")
    repaired = mixed_pdf(tmp_path / "ocr.pdf", mode="ocr")
    original_id = doc_id(raw)
    assert upload(client, raw).status_code == 422

    def call_api(base, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        return {"_failure": response.json()["error"]} if response.is_error else response.json()

    monkeypatch.setattr("dlrag.ui.client.call_api", call_api)
    def file_uploader(*args, key=None, **kwargs):
        if key == "recovery_pdf_" + original_id:
            return SimpleNamespace(name=repaired.name, getvalue=repaired.read_bytes)
        return None

    monkeypatch.setattr("streamlit.file_uploader", file_uploader)
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"))
    app.query_params["lang"] = language
    app.run()
    app.sidebar.radio[0].set_value("上传与管理").run()
    app.sidebar.radio[1].set_value("文献管理").run()
    assert any(expander.label == panel for expander in app.expander)
    app.selectbox(key="recovery_document").set_value(original_id).run()
    assert not app.exception
    assert any(link.proto.url.endswith(f"/{original_id}/file#page=2") for link in app.get("link_button"))
    next(button for button in app.button if button.label == action).click().run()
    assert not app.exception
    assert any(message.value == success for message in app.success)
    assert any(link.proto.url.endswith(f"/{doc_id(repaired)}/file") for link in app.get("link_button"))
    assert not any(button.label == action for button in app.button)
    assert cases(client)[0]["status"] == "recovered"
