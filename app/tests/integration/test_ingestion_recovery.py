"""COL-001 service decisions; synthetic PDFs and injected failures, no model API."""
import hashlib
from unittest.mock import Mock

import fitz
import pytest

from dlrag.retrieval.errors import ProjectError
from dlrag.retrieval.retriever import Retriever


def test_ready_duplicate_skips_parse_build_and_embedding(services, imported, pdf, monkeypatch):
    before = services.manifest()
    chunks = services.library.list_chunks()
    parse = Mock(side_effect=AssertionError("ready duplicate must not parse"))
    build = Mock(side_effect=AssertionError("ready duplicate must not rebuild"))
    encode = Mock(side_effect=AssertionError("ready duplicate must not embed"))
    monkeypatch.setattr(services.library, "_parse_document", parse)
    monkeypatch.setattr(services.retriever, "build", build)
    monkeypatch.setattr(services.retriever.backend, "encode", encode)
    with pytest.warns(UserWarning, match="metadata"):
        result = services.ingest(str(pdf), {"title": "Do not overwrite stored title", "topics": ["自然科学"]})
    assert result == imported
    assert result["document"]["doc_id"] == "d_" + hashlib.sha256(pdf.read_bytes()).hexdigest()
    assert services.manifest() == before
    assert services.library.list_chunks() == chunks
    parse.assert_not_called()
    build.assert_not_called()
    encode.assert_not_called()


@pytest.mark.parametrize("failure", ["embedding", "pointer_switch"])
def test_index_failure_keeps_old_service_and_retry_reuses_parsed_content(
        services, imported, tmp_path, monkeypatch, failure):
    import dlrag.retrieval.retriever as retriever_module

    path = tmp_path / "second.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((60, 90), "Accession recovery evidence. Second independent document.")
        pdf.save(path)
    new_id = "d_" + hashlib.sha256(path.read_bytes()).hexdigest()
    old_manifest = services.manifest()
    old_hits = services.retriever.search("Semantic", mode="keyword")
    assert old_hits
    with monkeypatch.context() as injected:
        if failure == "embedding":
            injected.setattr(services.retriever.backend, "encode",
                            Mock(side_effect=ProjectError("EMBEDDING_UNAVAILABLE", "injected outage")))
        else:
            replace = retriever_module.os.replace

            def fail_pointer(source, target):
                if target.name == "current.json":
                    raise OSError("injected pointer switch failure")
                return replace(source, target)

            injected.setattr(retriever_module.os, "replace", fail_pointer)
        with pytest.raises(ProjectError):
            services.ingest(str(path), {"title": "Recovery sample", "topics": ["自然科学"]})
    pending = services.library.get_document(new_id)
    assert pending["status"] == "indexing"
    assert pending["error_code"] == ("EMBEDDING_UNAVAILABLE" if failure == "embedding" else "INDEX_BUILD_FAILED")
    assert services.library.get_document(imported["document"]["doc_id"])["status"] == "ready"
    assert services.manifest() == old_manifest
    assert services.retriever.search("Semantic", mode="keyword") == old_hits
    # A new reader sees the old on-disk pointer as well as the old in-memory view.
    reader = Retriever(str(services.settings.index_dir), services.retriever.backend,
                       services.retriever.settings)
    assert reader.load() == old_manifest
    chunks = services.library.list_chunks(include_indexing=True)
    new_chunks = [c for c in chunks if c["doc_id"] == new_id]
    assert new_chunks and not list(services.settings.index_dir.glob(".building_*"))
    parse = Mock(side_effect=AssertionError("saved content must be reused on index retry"))
    encode = Mock(wraps=services.retriever.backend.encode)
    monkeypatch.setattr(services.library, "_parse_document", parse)
    monkeypatch.setattr(services.retriever.backend, "encode", encode)
    result = services.ingest(str(path), {"title": "Recovery sample", "topics": ["自然科学"]})
    parse.assert_not_called()
    assert encode.call_count == 1
    assert result["document"]["status"] == "ready" and result["document"]["error_code"] is None
    assert result["index_version"] != old_manifest["index_version"]
    assert services.manifest()["document_count"] == 2
    assert services.library.list_chunks() == chunks
    assert reader.load() == services.manifest()
    for chunk in new_chunks:
        page = services.library.get_page(new_id, chunk["pdf_page"])
        assert page["normalized_text"][chunk["page_char_start"]:chunk["page_char_end"]] == chunk["text"]
