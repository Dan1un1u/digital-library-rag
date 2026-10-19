"""ING-002: a visually readable embedded font can have an unusable text map."""
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import Mock

import fitz
import pytest

from dlrag.ingestion.fulltext import require_complete_text
from dlrag.ingestion.text_quality import encoding_evidence, TextLayerReviewRequired


def encoded_pdf(path, *, broken=True):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_font(fontname="quality-fixture", fontbuffer=fitz.Font("tiro").buffer)
        page.insert_textbox(fitz.Rect(45, 70, 550, 750),
                            "Synthetic body for text quality and search.\n" * 25,
                            fontname="quality-fixture", fontsize=12)
        if broken:
            # Glyphs still paint correctly, but CID numbers become characters.
            for font in page.get_fonts():
                pdf.xref_set_key(font[0], "ToUnicode", "null")
        pdf.save(path)
    return path


def test_unusable_font_mapping_cannot_become_ready(client, services, imported, tmp_path):
    path = encoded_pdf(tmp_path / "broken-map.pdf")
    raw = path.read_bytes()
    before = services.manifest()
    chunks = services.library.list_chunks()
    response = client.post("/documents", files={"file": (path.name, raw, "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEXT_LAYER_REVIEW_REQUIRED"
    doc_id = "d_" + hashlib.sha256(raw).hexdigest()
    assert services.library.get_document(doc_id)["status"] == "failed"
    assert services.library.get_page(doc_id, 1) is None
    assert services.manifest() == before and services.library.list_chunks() == chunks
    assert path.read_bytes() == raw


@pytest.mark.parametrize("text", [
    "A readable body with vocabulary unseen by any dictionary.\n" * 20,
    "中文古文天地玄黄，希腊字母αβγ与数学∑∞≤≥，العربية الفرنسية\n" * 20,
    "x = y + 12.5 / (2*pi)\t\r\n" * 20,
    "Legitimate private-use mathematical glyph \ue000 and accents é à ü. " * 20,
    "body" * 10 + "\x03" * 7,
    "body" * 1000 + "\x03" * 8,
])
def test_languages_math_whitespace_and_incidental_noise_are_not_rejected(text):
    assert encoding_evidence(text) is None
    require_complete_text([{"pdf_page": 1, "normalized_text": text, "raw_text": text}])


@pytest.mark.parametrize("character", ["\x00", "\x03", "\x1f", "\x7f", "\x80", "\ufffd"])
def test_dense_controls_and_replacement_characters_need_review(character):
    text = ("Valid" + character) * 20
    evidence = encoding_evidence(text)
    assert evidence["suspect_characters"] == 20
    with pytest.raises(TextLayerReviewRequired) as caught:
        require_complete_text([{"pdf_page": 2, "normalized_text": text, "raw_text": text}])
    assert caught.value.review["suspect_pages"] == [2]
    assert "Valid" not in json.dumps(caught.value.public_error())


def test_correct_unicode_mapping_is_preserved(client, tmp_path):
    path = encoded_pdf(tmp_path / "good-map.pdf", broken=False)
    result = client.post("/documents", files={"file": (path.name, path.read_bytes(), "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    assert result.status_code == 200 and result.json()["document"]["status"] == "ready"


def wait(client, ident):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        job = client.get("/document-jobs/" + ident).json()
        if job["stage"] in {"done", "error"}:
            return job
        time.sleep(.01)
    pytest.fail("job did not terminate")


def test_async_duplicate_retry_and_corrected_copy_preserve_failed_original(client, services, imported, tmp_path, monkeypatch):
    bad = encoded_pdf(tmp_path / "broken.pdf")
    raw = bad.read_bytes()
    build = Mock(side_effect=AssertionError("Corrupt text must not reach vectors"))
    original = services.retriever.build
    monkeypatch.setattr(services.retriever, "build", build)
    before = services.manifest()
    for _ in range(2):
        uploaded = client.post("/documents/jobs", files={"file": (bad.name, raw, "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
        job = wait(client, uploaded.json()["job_id"])
        assert job["stage"] == "error" and job["error"]["code"] == "TEXT_LAYER_REVIEW_REQUIRED"
    ident = "d_" + hashlib.sha256(raw).hexdigest()
    with pytest.raises(TextLayerReviewRequired):
        services.library.retry_document(ident, services.settings.chunking_config.model_dump())
    assert services.library.get_page(ident, 1) is None and services.manifest() == before
    build.assert_not_called()
    monkeypatch.setattr(services.retriever, "build", original)
    good = encoded_pdf(tmp_path / "repaired-copy.pdf", broken=False)
    response = client.post("/documents", files={"file": (good.name, good.read_bytes(), "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    assert response.status_code == 200 and services.library.get_document(ident)["status"] == "failed"


def test_save_boundary_checks_raw_text_even_without_diagnostic(services, tmp_path):
    path = encoded_pdf(tmp_path / "source.pdf", broken=False)
    doc = services.library.register_document(str(path), {})
    pages = [{"pdf_page": 1, "raw_text": "raw\x03" * 30, "normalized_text": "body", "diagnostics": []}]
    with pytest.raises(TextLayerReviewRequired):
        services.library.save_parsed_content(doc["doc_id"], pages, [], services.settings.chunking_config.model_dump(), "fixture")
    assert services.library.get_page(doc["doc_id"], 1) is None


def test_forged_code_does_not_echo_provider_or_pdf_body(client, services, tmp_path, monkeypatch):
    from dlrag.ingestion.errors import ProjectError
    path = encoded_pdf(tmp_path / "source.pdf", broken=False)
    monkeypatch.setattr(services, "ingest", Mock(side_effect=ProjectError("TEXT_LAYER_REVIEW_REQUIRED", "private-provider-body")))
    response = client.post("/documents/jobs", files={"file": (path.name, path.read_bytes(), "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    job = wait(client, response.json()["job_id"])
    assert job["error"]["code"] == "TEXT_LAYER_REVIEW_REQUIRED" and "private-provider-body" not in json.dumps(job)


def test_management_shows_text_review_and_keeps_original(client, tmp_path, monkeypatch):
    from streamlit.testing.v1 import AppTest
    path = encoded_pdf(tmp_path / "bad.pdf")
    client.post("/documents", files={"file": (path.name, path.read_bytes(), "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    monkeypatch.setattr("dlrag.ui.client.call_api", lambda base, method, path, **kw: client.request(method, path, **kw).json())
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"), default_timeout=20).run()
    app.sidebar.radio[0].set_value("上传与管理").run()
    app.sidebar.radio[1].set_value("文献管理").run()
    assert not app.exception
    assert any("待核对正文" in c.value for c in app.caption)
    assert any("编码异常" in e.value and "第 1 页" in e.value for e in app.error)
    assert any(b.label == "阅读原文" for b in app.get("link_button"))
