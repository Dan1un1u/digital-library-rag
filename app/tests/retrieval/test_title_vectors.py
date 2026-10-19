"""RET-001: title queries need a document title in the dense representation."""
import numpy as np

from dlrag.retrieval import Retriever

TITLE = "The Death of the Author"
CONFIG = {"count_mode": "character", "tokenizer_name": None, "tokenizer_revision": None,
          "max_tokens": 400, "overlap_tokens": 50, "max_chars": 1200, "overlap_chars": 150}


class TitleAwareEmbedding:
    model = "controlled-title-representation"
    revision = "1"
    dimension = 2

    def encode(self, texts):
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
