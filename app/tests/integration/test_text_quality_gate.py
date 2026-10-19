"""ING-002: a visually readable embedded font can have an unusable text map."""
import hashlib
from pathlib import Path

import fitz


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
    response = client.post("/documents", files={"file": (path.name, raw, "application/pdf")})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TEXT_LAYER_REVIEW_REQUIRED"
    doc_id = "d_" + hashlib.sha256(raw).hexdigest()
    assert services.library.get_document(doc_id)["status"] == "failed"
    assert services.library.get_page(doc_id, 1) is None
    assert services.manifest() == before and services.library.list_chunks() == chunks
    assert path.read_bytes() == raw
