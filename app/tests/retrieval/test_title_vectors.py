"""RET-001: title queries need a document title in the dense representation."""
import numpy as np
import copy
import json
import pytest

from dlrag.retrieval import Retriever, ProjectError
from dlrag.retrieval.retriever import VECTOR_TEXT_POLICY

TITLE = "The Death of the Author"
CONFIG = {"count_mode": "character", "tokenizer_name": None, "tokenizer_revision": None,
          "max_tokens": 400, "overlap_tokens": 50, "max_chars": 1200, "overlap_chars": 150}


class TitleAwareEmbedding:
    model = "controlled-title-representation"
    revision = "1"
    dimension = 2

    def __init__(self):
        self.calls = []

    def encode(self, texts):
        self.calls.append(list(texts))
        return np.asarray([[1., 0.] if TITLE in t else [0., 1.] if t == "An essay about narrative voice."
                           else [.8, .6] for t in texts], dtype=np.float32)


def chunk(number, title, text):
    return {"chunk_id": "c_" + str(number), "doc_id": "d_" + str(number), "pdf_page": 1,
            "printed_page": None, "section": None, "text": text,
            "page_char_start": 0, "page_char_end": len(text), "token_count": None,
            "document": {"title": title, "authors": [], "year": 1967, "topics": [], "language": "en"}}


def test_title_only_vector_query_retrieves_the_document_with_body_provenance(tmp_path):
    chunks = [chunk(0, TITLE, "An essay about narrative voice.")] + [
        chunk(i, "Other work " + str(i), "A passage about authors and writing.") for i in range(1, 7)]
    engine = Retriever(str(tmp_path / "index"), TitleAwareEmbedding(), {"chunking_config": CONFIG})
    engine.build(chunks)
    hits = engine.search(TITLE, mode="vector", top_k=5)
    assert hits[0]["chunk"]["doc_id"] == "d_0"
    assert hits[0]["chunk"]["text"] == "An essay about narrative voice."
    assert hits[0]["matched_by"] == ["vector"]


def test_only_embedding_input_gets_context_while_query_and_quotes_stay_original(tmp_path):
    backend = TitleAwareEmbedding()
    original = [chunk(0, TITLE, "An essay about narrative voice.")]
    frozen = copy.deepcopy(original)
    engine = Retriever(str(tmp_path / "index"), backend, {"chunking_config": CONFIG})
    manifest = engine.build(original)
    hits = engine.search(TITLE, mode="vector", top_k=5)
    assert backend.calls[0] == ["Title: " + TITLE + "\n\nAn essay about narrative voice."]
    assert backend.calls[-1] == [TITLE]
    assert original == frozen and hits[0]["chunk"] == original[0]
    assert manifest["retrieval_config"]["vector_text_policy"] == VECTOR_TEXT_POLICY


def test_persisted_title_representation_reloads_and_searches(tmp_path):
    path = str(tmp_path / "index")
    first = Retriever(path, TitleAwareEmbedding(), {"chunking_config": CONFIG})
    manifest = first.build([chunk(0, TITLE, "An essay about narrative voice.")])
    second = Retriever(path, TitleAwareEmbedding(), {"chunking_config": CONFIG})
    assert second.load() == manifest
    assert second.search(TITLE, mode="vector")[0]["chunk"]["doc_id"] == "d_0"


@pytest.mark.parametrize("policy", [None, "body-only-v1", "unrecognised-policy"])
def test_old_or_other_text_policies_cannot_silently_reuse_vectors(tmp_path, policy):
    engine = Retriever(str(tmp_path / "index"), TitleAwareEmbedding(), {"chunking_config": CONFIG})
    manifest = engine.build([chunk(0, TITLE, "An essay about narrative voice.")])
    path = tmp_path / "index" / manifest["index_version"] / "manifest.json"
    saved = json.loads(path.read_text())
    if policy is None:
        saved["retrieval_config"].pop("vector_text_policy")
    else:
        saved["retrieval_config"]["vector_text_policy"] = policy
    path.write_text(json.dumps(saved), encoding="utf-8")
    with pytest.raises(ProjectError) as caught:
        engine.load()
    assert caught.value.code == "EMBEDDING_MISMATCH"
    assert engine.get_manifest() == manifest


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid"])
def test_filters_still_exclude_a_title_match_before_ranking(tmp_path, mode):
    wrong_year = chunk(0, TITLE, "An essay about narrative voice.")
    eligible = chunk(1, "Other work", "A passage about authors and writing.")
    eligible["document"]["year"] = 2020
    engine = Retriever(str(tmp_path / "index"), TitleAwareEmbedding(), {"chunking_config": CONFIG})
    engine.build([wrong_year, eligible])
    assert all(h["chunk"]["doc_id"] != "d_0" for h in engine.search("authors", {"year_from": 2020}, mode))
