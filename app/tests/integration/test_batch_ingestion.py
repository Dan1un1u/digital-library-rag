"""Batch isolation, recovery, and exact incrementality through the normal entry points."""
import json
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
import pytest

from dlrag.api.main import create_app
from dlrag.api.services import assemble
from dlrag.retrieval.retriever import Retriever
from dlrag.shared.config import Settings
from scripts.seed_demo import create_pdf


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    service = assemble(Settings(app_mode="mock", data_dir=root, _env_file=None))
    with TestClient(create_app(services=service)) as client:
        yield client, service


def pdf(tmp_path, name):
    path = tmp_path / (name + ".pdf")
    create_pdf(path, [f"Study of {name} and reproducible indexing. A full text passage."])
    return path


def metadata(title):
    return {"title": title, "year": 2024, "authors": ["Case Author"], "topics": ["自然科学"]}


def send_batch(client, entries):
    files = [("files", (item.name, item.read_bytes(), "application/pdf")) for item, meta in entries]
    response = client.post("/documents/batch/jobs", files=files,
                           data={"metadata_json": json.dumps([meta for item, meta in entries])})
    assert response.status_code == 202, response.text
    for _ in range(250):
        state = client.get("/document-jobs/" + response.json()["job_id"]).json()
        if state["stage"] in {"done", "error"}:
            assert state["stage"] == "done", state
            return state["result"]
        time.sleep(0.02)
    pytest.fail("Batch job did not finish")


def test_batch_has_single_publication_and_only_new_encodes(library, tmp_path, monkeypatch):
    client, service = library
    old = service.ingest(str(pdf(tmp_path, "old research")), metadata("old research"))
    before = old["index_version"]
    original = service.retriever.backend.encode
    calls = []
    def count(texts):
        calls.append(len(texts))
        return original(texts)
    monkeypatch.setattr(service.retriever.backend, "encode", count)
    entries = [(pdf(tmp_path, name), metadata(name)) for name in ("alpha", "beta")]
    result = send_batch(client, entries)
    assert [item["status"] for item in result["items"]] == ["ready", "ready"]
    assert calls == [2]
    assert result["index_version"] != before
    assert len(list(Path(service.settings.index_dir).glob("idx_*"))) == 2
    for query in ("old research", "alpha", "beta"):
        hits = client.post("/search", json={"query": query, "mode": "hybrid"}).json()["documents"]
        assert any(doc["title"] == query for doc in hits)
    repeated = send_batch(client, entries)
    assert repeated["index_version"] == result["index_version"]
    assert len(service.library.list_documents()) == 3


def test_partial_batch_preserves_valid_documents(library, tmp_path):
    client, service = library
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a PDF")
    good = pdf(tmp_path, "sound content")
    result = send_batch(client, [(broken, metadata("broken")), (good, metadata("sound content"))])
    assert [r["status"] for r in result["items"]] == ["failed", "ready"]
    assert result["items"][0]["error"]["code"] == "INVALID_PDF"
    assert [doc["title"] for doc in service.library.list_documents()] == ["sound content"]


def test_failed_batch_retries_from_parsed_documents(library, tmp_path, monkeypatch):
    client, service = library
    previous = service.ingest(str(pdf(tmp_path, "existing item")), metadata("existing item"))["index_version"]
    original = service.retriever.backend.encode
    def fail(_):
        raise RuntimeError("encoder is unavailable")
    monkeypatch.setattr(service.retriever.backend, "encode", fail)
    entries = [(pdf(tmp_path, "retry"), metadata("retry"))]
    result = send_batch(client, entries)
    assert result["index_error"]
    assert result["items"][0]["status"] == "indexing"
    assert result["index_version"] == previous
    old = client.post("/search", json={"query": "existing item", "mode": "keyword"}).json()
    assert old["documents"][0]["title"] == "existing item"
    monkeypatch.setattr(service.retriever.backend, "encode", original)
    retry = send_batch(client, entries)
    assert retry["items"][0]["status"] == "ready"
    assert len(service.library.list_documents()) == 2
    assert retry["index_version"] != previous


def test_reload_reuses_vectors_and_reencodes_changed_title(library, tmp_path, monkeypatch):
    _, service = library
    service.ingest(str(pdf(tmp_path, "change")), metadata("old title"))
    service.ingest(str(pdf(tmp_path, "other")), metadata("other title"))
    base = service.retriever
    loaded = Retriever(str(base.index_dir), base.backend, base.settings)
    loaded.load()
    chunks = service.library.list_chunks()
    chunks[0]["document"]["title"] = "revised title"
    original = loaded.backend.encode
    calls = []
    def count(texts):
        calls.append(len(texts))
        return original(texts)
    monkeypatch.setattr(loaded.backend, "encode", count)
    loaded.build(chunks)
    assert calls == [1]
    incremental = loaded._snapshot[1]
    reference = Retriever(str(tmp_path / "full-index"), loaded.backend, loaded.settings)
    reference.build(chunks)
    np.testing.assert_allclose(incremental, reference._snapshot[1])
    monkeypatch.setattr(loaded.backend, "revision", "different")
    loaded.build(chunks)
    assert calls[-1] == 2


def test_batch_manage_page_reviews_two_pdfs_and_submits_once(library, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from streamlit.testing.v1 import AppTest

    client, service = library
    paths = [pdf(tmp_path, name) for name in ("paper one", "paper two")]
    uploads = [SimpleNamespace(name=path.name, getvalue=path.read_bytes) for path in paths]
    monkeypatch.setattr("streamlit.file_uploader", lambda *args, **kwargs: uploads
                        if kwargs.get("accept_multiple_files") else None)
    posted = []
    def call_api(base, method, path, **kwargs):
        if method == "POST":
            posted.append(path)
        response = client.request(method, path, **kwargs)
        return {"_failure": response.json()["error"]} if response.is_error else response.json()
    monkeypatch.setattr("dlrag.ui.client.call_api", call_api)
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"), default_timeout=15)
    app.query_params["lang"] = "en"
    app.run()
    app.sidebar.radio[0].set_value("上传与管理").run()
    app.sidebar.radio[1].set_value("批量入库").run()
    next(button for button in app.button if button.label == "Extract metadata for this batch").click().run()
    for index, field in enumerate([value for value in app.text_input if value.label == "Title"]):
        field.set_value(f"Confirmed paper {index+1}")
    for field in [value for value in app.selectbox if value.label == "Subject area"]:
        field.set_value("自然科学")
    next(button for button in app.button if button.label == "Publish batch").click().run()
    assert not app.exception
    assert posted.count("/documents/metadata/jobs") == 2
    assert posted.count("/documents/batch/jobs") == 1
    assert {row["title"] for row in service.library.list_documents()} == {"Confirmed paper 1", "Confirmed paper 2"}
