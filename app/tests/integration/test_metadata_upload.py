import json
from pathlib import Path
from types import SimpleNamespace

import fitz
from streamlit.testing.v1 import AppTest


def paper_bytes(title="Original title", author="Doe, Jane; John Smith"):
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 60), "Evidence Search for Libraries", fontsize=20)
        page.insert_text((40, 110), "Alice Smith and Bob Jones", fontsize=12)
        page.insert_text((40, 160), "This paper describes BM25 and semantic retrieval methods.", fontsize=10)
        pdf.set_metadata({"title": title, "author": author})
        return pdf.tobytes()


def test_preview_does_not_ingest_and_user_can_override(client, services):
    data = paper_bytes()
    r = client.post("/documents/metadata", files={"file": ("paper.pdf", data, "application/pdf")})
    assert r.status_code == 200
    m = r.json()["metadata"]
    assert m["title"] == "Original title" and m["authors"] == ["Doe, Jane", "John Smith"]
    assert services.library.list_documents(include_nonready=True) == []
    assert services.retriever.get_manifest() is None
    assert not list((services.settings.data_dir / "tmp").iterdir())
    m["title"] = "User corrected title"
    m["topics"] = ["自然科学"]  # User selects a discipline after preview.
    imported = client.post("/documents", files={"file": ("paper.pdf", data, "application/pdf")}, data={"metadata_json": json.dumps(m)})
    assert imported.status_code == 200
    assert imported.json()["document"]["title"] == "User corrected title"
    assert imported.json()["document"]["authors"] == ["Doe, Jane", "John Smith"]


def test_preview_file_validation_and_cleanup(client, services):
    assert client.post("/documents/metadata", files={"file": ("a.txt", b"bad", "text/plain")}).status_code == 415
    assert client.post("/documents/metadata", files={"file": ("a.pdf", b"bad", "application/pdf")}).status_code == 422
    services.settings.max_upload_mb = 1
    assert client.post("/documents/metadata", files={"file": ("a.pdf", b"%PDF" + b"0" * 1048576, "application/pdf")}).status_code == 413
    assert services.library.list_documents(include_nonready=True) == []
    assert not list((services.settings.data_dir / "tmp").iterdir())


def test_ui_prefills_keeps_edits_and_resets_for_new_file(client, monkeypatch):
    calls = []
    def local_api(base, method, path, **kwargs):
        calls.append(path)
        response = client.request(method, path, **kwargs)
        if response.is_error:
            return {"_failure": response.json()["error"]}
        return response.json()
    monkeypatch.setattr("dlrag.ui.client.call_api", local_api)
    data = paper_bytes()
    selection = {"file": SimpleNamespace(name="first.pdf", getvalue=lambda: data)}
    monkeypatch.setattr("streamlit.file_uploader", lambda *a, **k: selection["file"])
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"), default_timeout=20).run()
    app.sidebar.radio[0].set_value("上传与管理").run()
    assert not app.exception
    assert app.text_input(key="upload_title").value == "Original title"
    assert app.text_area(key="upload_authors").value == "Doe, Jane\nJohn Smith"
    app.text_input(key="upload_title").set_value("My corrected title")
    app.selectbox(key="upload_domain").set_value("社会科学")
    next(w for w in app.button if w.label == "导入文献").click().run()
    assert not app.exception
    assert client.get("/documents").json()["documents"][0]["title"] == "My corrected title"
    assert "社会科学" in client.get("/documents").json()["documents"][0]["topics"]
    assert calls.count("/documents/metadata/jobs") == 1
    next_data = paper_bytes(title="New document title", author="Bob Jones")
    selection["file"] = SimpleNamespace(name="second.pdf", getvalue=lambda: next_data)
    app.run()
    assert not app.exception
    assert app.text_input(key="upload_title").value == "New document title"
    assert app.text_area(key="upload_authors").value == "Bob Jones"
    assert app.selectbox(key="upload_domain").value is None
    assert calls.count("/documents/metadata/jobs") == 2
    selection["file"] = None
    app.run()
    assert not app.exception
    assert app.text_input(key="upload_title").value == ""
    assert app.text_area(key="upload_authors").value == ""
    assert "upload_preview" not in app.session_state
    assert "upload_fingerprint" not in app.session_state
