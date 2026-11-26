"""Post-accession catalogue review, correction, and publication consistency."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from streamlit.testing.v1 import AppTest

from dlrag.api.main import create_app
from dlrag.api.services import Services, assemble
from dlrag.shared.config import Settings
from scripts.seed_demo import create_pdf


@pytest.fixture
def catalogue(tmp_path):
    settings = Settings(app_mode="mock", data_dir=tmp_path / "catalogue", _env_file=None)
    service = assemble(settings)
    with TestClient(create_app(services=service), raise_server_exceptions=False) as client:
        pdf = tmp_path / "report.pdf"
        create_pdf(pdf, ["Community Impact of an Adult Education Programme. Published in 2024. "
                         "An adult education programme improves access to library resources."])
        metadata = {"title": "Community Impact of an Adult Education Programme", "year": 2022,
                    "authors": ["Adult Education Programme"], "topics": ["自然科学", "评估"]}
        response = client.post("/documents", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
                               data={"metadata_json": json.dumps(metadata)})
        assert response.status_code == 200
        yield client, service, response.json()["document"]


def correction(document):
    return {"authors": ["Li Wei", "Ada Chen"], "year": 2024, "discipline": "社会科学",
            "expected_updated_at": document["updated_at"], "evidence_page": 1, "note": "Verified PDF front matter."}


def test_review_flags_and_correction_refresh_catalogue_search_and_history(catalogue):
    client, service, old = catalogue
    doc_id = old["doc_id"]
    review = client.get("/documents/metadata/review")
    assert review.status_code == 200
    issues = review.json()["records"][0]["issues"]
    assert {item["code"] for item in issues} == {"AUTHOR_MATCHES_TITLE", "VERSION_YEAR_CHECK"}
    response = client.patch(f"/documents/{doc_id}/metadata", json=correction(old))
    assert response.status_code == 200, response.text
    document = response.json()["document"]
    assert document["doc_id"] == old["doc_id"] and document["file_sha256"] == old["file_sha256"]
    assert document["authors"] == ["Li Wei", "Ada Chen"] and document["year"] == 2024
    assert document["topics"] == ["社会科学", "评估"]
    assert client.get("/documents/metadata/review").json()["records"][0]["issues"] == []
    matching = client.post("/search", json={"query": "adult education", "mode": "hybrid",
                        "filters": {"year_from": 2024, "topics": ["社会科学"]}}).json()
    assert matching["hits"][0]["chunk"]["document"]["authors"] == document["authors"]
    history = client.get(f"/documents/{doc_id}/metadata/revisions").json()["revisions"]
    assert history[0]["before"]["year"] == 2022 and history[0]["after"]["year"] == 2024
    assert history[0]["evidence_page"] == 1 and history[0]["source"] == "manual_review"
    assert client.patch(f"/documents/{doc_id}/metadata", json=correction(old)).status_code == 409


def test_failure_keeps_original_metadata_and_index(catalogue, monkeypatch):
    client, service, old = catalogue
    previous = service.manifest()["index_version"]
    def fail(_):
        raise RuntimeError("index unavailable")
    monkeypatch.setattr(service.retriever, "build", fail)
    path = f"/documents/{old['doc_id']}/metadata"
    assert client.patch(path, json=correction(old)).status_code == 500
    unchanged = client.get("/documents/" + old["doc_id"]).json()["document"]
    assert unchanged == old
    assert client.get(path + "/revisions").json()["revisions"] == []
    assert service.manifest()["index_version"] == previous



@pytest.mark.parametrize("next_write", ["correction", "import"])
def test_live_rollback_keeps_search_unavailable_until_the_committed_index_loads(
    catalogue, monkeypatch, tmp_path, next_write
):
    client, service, old = catalogue
    path = f"/documents/{old['doc_id']}/metadata"
    # An SQLite transaction may reject the commit after the index has been published.
    with closing(sqlite3.connect(service.settings.db_path)) as db, db:
        db.execute("CREATE TABLE test_parent (id TEXT PRIMARY KEY)")
        db.execute("CREATE TABLE test_child (id TEXT REFERENCES test_parent(id) DEFERRABLE INITIALLY DEFERRED)")
        db.execute("""
            CREATE TRIGGER fail_revision_commit AFTER UPDATE OF authors_json ON documents
            BEGIN INSERT INTO test_child VALUES (NEW.doc_id); END
        """)

    def unreadable_index():
        raise OSError("simulated transient index read failure")

    with monkeypatch.context() as patch:
        patch.setattr(service.retriever, "load", unreadable_index)
        assert client.patch(path, json=correction(old)).status_code == 500
    assert client.get(f"/documents/{old['doc_id']}").json()["document"]["authors"] == old["authors"]
    query = {"query": "adult education", "mode": "keyword"}
    assert client.post("/search", json=query).status_code == 503
    marker_path = service.settings.index_dir / ".pending-metadata-review.json"
    assert marker_path.exists()

    if next_write == "correction":
        with closing(sqlite3.connect(service.settings.db_path)) as db, db:
            db.execute("DROP TRIGGER fail_revision_commit")
        accepted = client.patch(path, json=correction(old))
        assert accepted.status_code == 200
        search = client.post("/search", json=query).json()
        assert search["hits"][0]["chunk"]["document"]["authors"] == accepted.json()["document"]["authors"]
    else:
        extra = tmp_path / "later.pdf"
        create_pdf(extra, ["LaterAcquisition describes a separate topic."])
        added = client.post("/documents", files={"file": (extra.name, extra.read_bytes(), "application/pdf")},
                            data={"metadata_json": json.dumps({"title": "LaterAcquisition", "topics": ["自然科学"]})})
        assert added.status_code == 200
        new_doc_id = added.json()["document"]["doc_id"]
        with TestClient(create_app(service.settings)) as restarted:
            search = restarted.post("/search", json={"query": "LaterAcquisition", "mode": "keyword"}).json()
            assert new_doc_id in {hit["doc_id"] for hit in search["documents"]}
    assert not marker_path.exists()

@pytest.mark.parametrize("startup", ["assembled", "injected", "injected_retry"])
def test_recover_from_crash_after_index_publication_before_database_commit(catalogue, startup, monkeypatch):
    _, service, old = catalogue
    from dlrag.api.metadata_review import prepare_recovery
    current = service.manifest()["index_version"]
    prepare_recovery(service.settings.index_dir, old["doc_id"], old["updated_at"], "uncommitted", current)
    chunks = service.library.list_chunks()
    chunks[0]["document"]["authors"] = ["Uncommitted author"]
    assert service.retriever.build(chunks)["index_version"] != current
    if startup.startswith("injected"):
        from dlrag.ingestion.library import LibraryStore
        from dlrag.retrieval.retriever import Retriever

        settings = service.settings
        library = LibraryStore(settings.db_path, settings.files_dir)
        retriever = Retriever(settings.index_dir, service.retriever.backend, service.retriever.settings)
        retriever.load()
        assert retriever.get_manifest()["index_version"] != current
        restarted = Services(settings, library=library, retriever=retriever)
        if startup == "injected_retry":
            def unavailable():
                raise OSError("simulated transient reload error")

            with monkeypatch.context() as patch:
                patch.setattr(retriever, "load", unavailable)
                with pytest.raises(OSError, match="simulated transient reload error"):
                    create_app(services=restarted)
            assert (settings.index_dir / ".pending-metadata-review.json").exists()
        app = create_app(services=restarted)
    else:
        app = create_app(service.settings)

    with TestClient(app) as client:
        detail = client.get(f"/documents/{old['doc_id']}").json()["document"]
        search = client.post("/search", json={"query": "adult education", "mode": "keyword"}).json()
        assert search["index_version"] == current
        assert search["hits"][0]["chunk"]["document"]["authors"] == detail["authors"] == old["authors"]
    assert not (service.settings.index_dir / ".pending-metadata-review.json").exists()



def test_injected_startup_keeps_the_committed_revision(catalogue):
    from dlrag.api.metadata_review import prepare_recovery
    from dlrag.retrieval.retriever import Retriever

    client, service, old = catalogue
    settings = service.settings
    retriever = Retriever(settings.index_dir, service.retriever.backend, service.retriever.settings)
    previous = retriever.load()["index_version"]
    response = client.patch(f"/documents/{old['doc_id']}/metadata", json=correction(old))
    assert response.status_code == 200
    saved = response.json()
    assert saved["index_version"] != previous
    intent = prepare_recovery(settings.index_dir, old["doc_id"], old["updated_at"],
                              saved["document"]["updated_at"], previous)
    injected = Services(settings, library=service.library, retriever=retriever)
    with TestClient(create_app(services=injected)) as restarted:
        result = restarted.post("/search", json={"query": "adult education", "mode": "keyword"}).json()
        assert result["index_version"] == saved["index_version"]
        assert result["hits"][0]["chunk"]["document"]["authors"] == saved["document"]["authors"]
    assert not intent.exists()

def test_existing_version_one_database_migrates_without_reingestion(catalogue):
    _, service, old = catalogue
    with sqlite3.connect(service.settings.db_path) as db:
        db.execute("DROP TABLE metadata_revisions")
        db.execute("PRAGMA user_version=1")
    reopened = assemble(service.settings).library
    assert reopened.get_document(old["doc_id"])["file_sha256"] == old["file_sha256"]
    assert reopened.metadata_history(old["doc_id"]) == []
    assert len(reopened.list_chunks()) > 0


def test_english_manage_page_exposes_repair_form(catalogue, monkeypatch):
    client, _, old = catalogue
    def call_api(base, method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        return {"_failure": response.json()["error"]} if response.is_error else response.json()

    monkeypatch.setattr("dlrag.ui.client.call_api", call_api)
    app = AppTest.from_file(str(Path(__file__).parents[2] / "src/dlrag/ui/app.py"))
    app.query_params["lang"] = "en"
    app.run()
    app.sidebar.radio[0].set_value("上传与管理").run()
    app.sidebar.radio[1].set_value("文献管理").run()
    assert any(item.label == "Metadata review and correction" for item in app.expander)
    app.selectbox(key="review_document").set_value(old["doc_id"]).run()
    assert not app.exception
    next(field for field in app.text_area if field.label.startswith("Authors")).set_value("Li Wei\nAda Chen")
    next(field for field in app.text_input if field.label.startswith("Version year")).set_value("2024")
    next(button for button in app.button if button.label == "Save correction").click().run()
    assert not app.exception
    assert any(message.value == "Correction saved." for message in app.success)
    revised = client.get("/documents/" + old["doc_id"]).json()["document"]
    assert revised["authors"] == ["Li Wei", "Ada Chen"] and revised["year"] == 2024
