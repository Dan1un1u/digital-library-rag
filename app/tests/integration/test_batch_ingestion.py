"""Batch isolation, recovery, and exact incrementality through the normal entry points."""
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
import pytest

from dlrag.api.main import create_app
from dlrag.api.services import Services, assemble
from dlrag.retrieval.retriever import Retriever
from dlrag.shared.config import Settings
from scripts.seed_demo import create_pdf


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    service = assemble(Settings(app_mode="mock", data_dir=root, _env_file=None))
    with TestClient(create_app(services=service), raise_server_exceptions=False) as client:
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



@pytest.mark.parametrize("failure", ["statement", "commit"])
@pytest.mark.parametrize("has_old_index", [True, False])
def test_ready_write_failure_preserves_publication_and_retries(library, tmp_path, has_old_index, failure):
    client, service = library
    previous = None
    if has_old_index:
        previous = service.ingest(str(pdf(tmp_path, "previous baseline")), metadata("previous baseline"))["index_version"]
    pointer = service.settings.index_dir / "current.json"
    previous_pointer = pointer.read_bytes() if has_old_index else None
    entries = [(pdf(tmp_path, name), metadata(name)) for name in ("QuasarProof", "NebulaProof")]
    ids = {"d_" + hashlib.sha256(item.read_bytes()).hexdigest() for item, _ in entries}
    failed = max(ids)
    with sqlite3.connect(service.settings.db_path) as db:
        if failure == "commit":
            db.execute("CREATE TABLE test_parent (id TEXT PRIMARY KEY)")
            db.execute("CREATE TABLE test_child (id TEXT REFERENCES test_parent(id) DEFERRABLE INITIALLY DEFERRED)")
            fault = "INSERT INTO test_child VALUES (NEW.doc_id);"
        else:
            fault = "SELECT RAISE(ABORT, 'simulated status write rejection');"
        db.execute(f"""
            CREATE TRIGGER fail_second_ready BEFORE UPDATE OF status ON documents
            WHEN NEW.status = 'ready' AND NEW.doc_id = '{failed}'
            BEGIN {fault} END
        """)

    result = send_batch(client, entries)
    assert result["index_error"]
    assert {item["status"] for item in result["items"]} == {"indexing"}
    assert {item["doc_id"] for item in result["items"]} == ids
    assert result["index_version"] == client.get("/health").json()["index_version"] == previous
    catalogue = client.get("/documents").json()["documents"]
    assert not ({row["doc_id"] for row in catalogue} & ids)
    found = client.post("/search", json={"query": "QuasarProof NebulaProof", "mode": "keyword"})
    if has_old_index:
        assert pointer.read_bytes() == previous_pointer
        assert found.status_code == 200 and found.json()["index_version"] == previous
        assert not ({row["doc_id"] for row in found.json()["documents"]} & ids)
    else:
        assert found.status_code == 503
        assert not pointer.exists()

    # Parsed data remain retryable and the successful retry publishes both documents.
    with sqlite3.connect(service.settings.db_path) as db:
        db.execute("DROP TRIGGER fail_second_ready")
    retry = send_batch(client, entries)
    assert {item["status"] for item in retry["items"]} == {"ready"}
    assert {item["doc_id"] for item in retry["items"]} == ids
    assert retry["index_version"] == client.get("/health").json()["index_version"]
    assert ids <= {row["doc_id"] for row in client.get("/documents").json()["documents"]}


@pytest.mark.parametrize("startup", ["assembled", "injected"])
@pytest.mark.parametrize("committed", [False, True])
def test_restart_reconciles_an_interrupted_index_publication(library, tmp_path, startup, committed):
    from dlrag.api.index_publication import prepare_index_publication
    from dlrag.ingestion.library import LibraryStore

    _, service = library
    previous = service.ingest(str(pdf(tmp_path, "prior article")), metadata("prior article"))["index_version"]
    settings = service.settings
    entry = pdf(tmp_path, "RestartCase")
    parsed = service.library.ingest_pdf(str(entry), metadata("RestartCase"), settings.chunking_config.model_dump())
    new_doc_id = parsed["doc_id"]
    intent = prepare_index_publication(settings.index_dir, [new_doc_id])
    written = service.retriever.build(service.library.list_chunks(include_indexing=True))["index_version"]
    assert written != previous
    if committed:
        service.library.set_documents_status([new_doc_id], "ready")

    if startup == "injected":
        store = LibraryStore(settings.db_path, settings.files_dir)
        retriever = Retriever(settings.index_dir, service.retriever.backend, service.retriever.settings)
        retriever.load()
        assert retriever.get_manifest()["index_version"] == written
        app = create_app(services=Services(settings, library=store, retriever=retriever))
    else:
        app = create_app(settings)
    with TestClient(app) as client:
        catalogue = client.get("/documents").json()["documents"]
        hits = client.post("/search", json={"query": "RestartCase", "mode": "keyword"}).json()
        assert (new_doc_id in {row["doc_id"] for row in catalogue}) == committed
        assert (new_doc_id in {row["doc_id"] for row in hits["documents"]}) == committed
        assert hits["index_version"] == (written if committed else previous)
    assert not intent.exists()

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
        data = response.json()
        if response.is_error:
            return {"_failure": data["error"]}
        if path.startswith("/document-jobs/") and data["stage"] == "done" and "metadata" in data["result"]:
            data["result"]["metadata"]["topics"] = ["自然科学", "BM25"]
        return data
    monkeypatch.setattr("dlrag.ui.client.call_api", call_api)
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"), default_timeout=15)
    app.query_params["lang"] = "en"
    app.run()
    app.sidebar.radio[0].set_value("上传与管理").run()
    app.sidebar.radio[1].set_value("批量入库").run()
    next(button for button in app.button if button.label == "Extract metadata for this batch").click().run()
    topic_fields = [value for value in app.text_input if (value.key or "").endswith("_topics")]
    assert [field.value for field in topic_fields] == ["BM25", "BM25"]
    topic_fields[0].set_value("Reviewed batch topic")
    for index, field in enumerate([value for value in app.text_input if value.label == "Title"]):
        field.set_value(f"Confirmed paper {index+1}")
    for field in [value for value in app.selectbox if value.label == "Subject area"]:
        field.set_value("自然科学")
    next(button for button in app.button if button.label == "Publish batch").click().run()
    assert not app.exception
    assert posted.count("/documents/metadata/jobs") == 2
    assert posted.count("/documents/batch/jobs") == 1
    documents = {row["title"]: row for row in service.library.list_documents()}
    assert set(documents) == {"Confirmed paper 1", "Confirmed paper 2"}
    assert set(documents["Confirmed paper 1"]["topics"]) == {"自然科学", "Reviewed batch topic"}
    assert set(documents["Confirmed paper 2"]["topics"]) == {"自然科学", "BM25"}
