"""ING-001: a text cover cannot make unrecognized scanned body pages ready."""
import hashlib

import fitz


def mixed_pdf(path, *, mode="scan", rotation=0):
    """Self-authored raster body, optionally with a real text/OCR layer."""
    with fitz.open() as image_source:
        p = image_source.new_page()
        p.insert_textbox(fitz.Rect(45, 100, 550, 700),
                         "Scanned body evidence must be searchable.\n" * 25, fontsize=12)
        raster = p.get_pixmap().tobytes("png")
    with fitz.open() as pdf:
        pdf.new_page().insert_text((45, 100), "A machine-readable catalogue cover.")
        p = pdf.new_page()
        if mode != "blank":
            p.insert_image(fitz.Rect(45, 45, 120, 120) if mode == "logo" else p.rect, stream=raster)
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
    doc_id = "d_" + hashlib.sha256(path.read_bytes()).hexdigest()
    doc = services.library.get_document(doc_id)
    assert doc["status"] == "failed" and doc["error_code"] == "FULLTEXT_REVIEW_REQUIRED"
    assert services.library.get_page(doc_id, 1) is None
    assert services.manifest() == before
    assert services.library.list_chunks(include_indexing=True) == chunks
    assert doc_id not in {d["doc_id"] for d in client.get("/documents").json()["documents"]}
