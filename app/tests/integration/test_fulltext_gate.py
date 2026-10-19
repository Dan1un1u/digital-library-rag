"""ING-001: a text cover cannot make unrecognized scanned body pages ready."""
import hashlib
import json
import time
from pathlib import Path
from unittest.mock import Mock

import fitz
import pytest
from streamlit.testing.v1 import AppTest

from dlrag.ingestion.fulltext import FulltextReviewRequired, require_complete_text, REVIEW_DIAGNOSTIC
from dlrag.ingestion.parser import parse_pdf


def mixed_pdf(path, *, mode="scan", rotation=0):
    """Self-authored raster body, optionally with a real text/OCR layer."""
    with fitz.open() as image_source:
        p = image_source.new_page()
        p.insert_textbox(fitz.Rect(45, 100, 550, 700),
                         "Scanned body evidence must be searchable.\n" * 25, fontsize=12)
        raster = p.get_pixmap().tobytes("png")
        p = image_source.new_page()
        blank = p.get_pixmap().tobytes("png")
    with fitz.open() as pdf:
        pdf.new_page().insert_text((45, 100), "A machine-readable catalogue cover.")
        p = pdf.new_page()
        if mode == "tiled":
            w, h = p.rect.width / 2, p.rect.height / 2
            for x, y in ((0, 0), (w, 0), (0, h), (w, h)):
                p.insert_image(fitz.Rect(x, y, x+w, y+h), stream=raster)
        elif mode not in {"blank", "vector"}:
            for _ in range(8 if mode == "overlapping_logos" else 1):
                p.insert_image(fitz.Rect(45, 45, 120, 120) if mode in {"logo", "overlapping_logos"}
                               else p.rect, stream=blank if mode == "blank_scan" else raster)
        if mode == "vector":
            p.draw_rect(fitz.Rect(50, 50, 500, 700), color=(0, 0, 0))
        if mode == "ocr":
            p.insert_textbox(fitz.Rect(45, 100, 550, 700),
                             "Scanned body evidence must be searchable.\n" * 25,
                             fontsize=12, render_mode=3)
        elif mode == "number":
            p.insert_text((290, 810), "2")
        p.set_rotation(rotation)
        pdf.save(path)
    return path


def test_mixed_scan_import_is_not_served(client, services, imported, tmp_path):
    path = mixed_pdf(tmp_path / "mixed.pdf")
    before = services.manifest()
    chunks = services.library.list_chunks()
    response = client.post("/documents", files={"file": (path.name, path.read_bytes(), "application/pdf")})
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "FULLTEXT_REVIEW_REQUIRED"
    assert response.json()["error"]["fulltext_review"]["suspect_pages"] == [2]
    doc_id = "d_" + hashlib.sha256(path.read_bytes()).hexdigest()
    doc = services.library.get_document(doc_id)
    assert doc["status"] == "failed" and doc["error_code"] == "FULLTEXT_REVIEW_REQUIRED"
    assert services.library.get_page(doc_id, 1) is None
    assert services.manifest() == before
    assert services.library.list_chunks(include_indexing=True) == chunks
    assert doc_id not in {d["doc_id"] for d in client.get("/documents").json()["documents"]}


@pytest.mark.parametrize("mode", ["blank", "blank_scan", "logo", "overlapping_logos", "vector", "ocr"])
def test_blank_small_graphic_and_readable_ocr_are_not_blocked(client, tmp_path, mode):
    path = mixed_pdf(tmp_path / "boundary.pdf", mode=mode)
    result = client.post("/documents", files={"file": (path.name, path.read_bytes(), "application/pdf")})
    assert result.status_code == 200, result.text
    assert result.json()["document"]["status"] == "ready"


@pytest.mark.parametrize("mode,rotation", [("scan", 90), ("scan", 180), ("scan", 270),
                                         ("number", 0), ("tiled", 0)])
def test_rotated_tiled_and_page_number_only_scans_require_review(tmp_path, mode, rotation):
    path = mixed_pdf(tmp_path / "scan.pdf", mode=mode, rotation=rotation)
    before = path.read_bytes()
    pages = parse_pdf(path)
    with pytest.raises(FulltextReviewRequired) as caught:
        require_complete_text(pages)
    assert caught.value.review["suspect_pages"] == [2]
    assert path.read_bytes() == before


def test_save_boundary_cannot_commit_flagged_partial_content(services, tmp_path):
    from dlrag.ingestion.chunker import chunk_pages
    path = mixed_pdf(tmp_path / "bypass.pdf")
    pages = parse_pdf(path)
    doc = services.library.register_document(str(path), {"title": "A direct caller"})
    config = services.settings.chunking_config.model_dump()
    chunks = chunk_pages(doc["doc_id"], pages, config)
    with pytest.raises(FulltextReviewRequired):
        services.library.save_parsed_content(doc["doc_id"], pages, chunks, config, "test")
    assert services.library.get_page(doc["doc_id"], 1) is None
    assert services.library.list_chunks(include_indexing=True) == []


def wait_job(client, ident):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        job = client.get("/document-jobs/" + ident).json()
        if job["stage"] in {"done", "error"}:
            return job
        time.sleep(.01)
    pytest.fail("import job did not terminate")


def test_async_review_survives_repeated_upload_and_explicit_retry(
        client, services, imported, tmp_path, monkeypatch):
    path = mixed_pdf(tmp_path / "scan.pdf")
    before = services.manifest()
    build = Mock(side_effect=AssertionError("suspect pages must not be embedded"))
    monkeypatch.setattr(services.retriever, "build", build)
    for attempt in range(2):
        response = client.post("/documents/jobs", files={"file": (path.name, path.read_bytes(), "application/pdf")})
        job = wait_job(client, response.json()["job_id"])
        assert job["stage"] == "error" and job["error"]["code"] == "FULLTEXT_REVIEW_REQUIRED"
        assert job["result"] is None
        assert "OCR" in job["error"]["message"]
        if attempt == 0:
            assert job["error"]["fulltext_review"]["suspect_pages"] == [2]
    doc_id = "d_" + hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(FulltextReviewRequired):
        services.library.retry_document(doc_id, services.settings.chunking_config.model_dump())
    assert services.library.get_document(doc_id)["status"] == "failed"
    assert services.manifest() == before
    build.assert_not_called()


def test_corrected_ocr_copy_can_be_imported_without_promoting_original(client, services, tmp_path):
    bad = mixed_pdf(tmp_path / "bad.pdf")
    assert client.post("/documents", files={"file": (bad.name, bad.read_bytes(), "application/pdf")}).status_code == 422
    fixed = mixed_pdf(tmp_path / "fixed.pdf", mode="ocr")
    response = client.post("/documents/jobs", files={"file": (fixed.name, fixed.read_bytes(), "application/pdf")})
    job = wait_job(client, response.json()["job_id"])
    assert job["stage"] == "done" and job["result"]["document"]["status"] == "ready"
    assert len(client.get("/documents").json()["documents"]) == 1
    assert {c["pdf_page"] for c in services.library.list_chunks()} == {1, 2}
    original_id = "d_" + hashlib.sha256(bad.read_bytes()).hexdigest()
    assert services.library.get_document(original_id)["status"] == "failed"


def test_review_error_does_not_expose_provider_exception(client, services, tmp_path, monkeypatch):
    # A forged error code must not let the async error path echo arbitrary text.
    from dlrag.ingestion.errors import ProjectError
    path = mixed_pdf(tmp_path / "sample.pdf")
    monkeypatch.setattr(services, "ingest", Mock(side_effect=ProjectError("FULLTEXT_REVIEW_REQUIRED", "private-provider-body")))
    job_id = client.post("/documents/jobs", files={"file": (path.name, path.read_bytes(), "application/pdf")}).json()["job_id"]
    job = wait_job(client, job_id)
    assert job["stage"] == "error" and "private-provider-body" not in json.dumps(job)


def test_management_ui_explains_review_and_keeps_source_access(client, services, tmp_path, monkeypatch):
    path = mixed_pdf(tmp_path / "review.pdf")
    client.post("/documents", files={"file": (path.name, path.read_bytes(), "application/pdf")})
    monkeypatch.setattr("dlrag.ui.client.call_api", lambda base, method, path, **kw: client.request(method, path, **kw).json())
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"), default_timeout=20).run()
    app.sidebar.radio[0].set_value("上传与管理").run()
    app.sidebar.radio[1].set_value("文献管理").run()
    assert not app.exception
    assert any("待核对正文" in c.value for c in app.caption)
    assert any("第 2 页" in e.value and "OCR" in e.value for e in app.error)
    assert any(b.label == "阅读原文" for b in app.get("link_button"))


def test_many_review_pages_have_compact_ranges_without_body_text():
    exc = FulltextReviewRequired(list(range(2, 22)), 21, 1)
    assert "2–21" in exc.message and len(exc.message) < 200
    assert exc.public_error()["fulltext_review"]["suspect_pages"] == list(range(2, 22))
