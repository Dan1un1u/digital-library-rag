import copy
import pytest

from dlrag.qa import QAEngine, ScriptedMockLLM, ProjectError
from dlrag.qa.demo import demo_chunk, FakeRetriever
from dlrag.qa.engine import DEFAULTS
from dlrag.qa.planner import original_plan, validate_plan
from dlrag.qa.retrieval import fuse_queries
from dlrag.qa.reranking import rerank, reference_features
from dlrag.qa.evidence import select_evidence, validate_hits


def chunk(cid, text, doc="d_paper", page=1, offset=0):
    c = demo_chunk()
    c.update(chunk_id=cid, doc_id=doc, text=text, pdf_page=page,
             page_char_start=offset, page_char_end=offset + len(text), char_count=len(text))
    c["document"].update(title="Synthetic paper", year=2024)
    return c


def hit(c, rank=1, version="idx_test"):
    return dict(rank=rank, chunk=c, scores=dict(bm25=None, cosine=.6, rrf=None, rerank=None),
                matched_by=["vector"], index_version=version)


def answer(cid):
    return dict(status="answered", claims=[dict(text="仅用于测试的结论", evidence_chunk_ids=[cid])], limitations=[])


def test_bilingual_two_searches_one_planning_call_preserves_filters():
    q = "模型如何处理长文本？"
    plan = {**original_plan(q), "english_query": "How do models process long texts?"}
    class Languages(FakeRetriever):
        def search(self, query, filters=None, mode="hybrid", top_k=20):
            self.calls.append((query, copy.deepcopy(filters), mode, top_k))
            c = chunk("en", "Models process long texts with a context window.") if query == plan["english_query"] else chunk("zh", "模型处理长文本。")
            return [hit(c)]
    retriever = Languages()
    llm = ScriptedMockLLM([plan, answer("en")])
    filters = dict(year_from=2020, year_to=2025, topics=["IR"])
    r = QAEngine(retriever, llm, {}).ask(dict(question=q, filters=filters))
    assert r["status"] == "answered" and len(llm.calls) == 2
    assert [c[0] for c in retriever.calls] == [q, plan["english_query"]]
    assert all(c[1] == filters and c[2:] == ("hybrid", 20) for c in retriever.calls)
    assert r["diagnostics"]["multi_query"] is True


def test_translation_missing_or_disabled_uses_one_query():
    q = "模型如何处理长文本？"
    plan = {**original_plan(q), "english_query": "How do models process long texts?"}
    r = FakeRetriever([chunk("body", "Models process long texts.")])
    llm = ScriptedMockLLM([plan, answer("body")])
    response = QAEngine(r, llm, dict(bilingual_retrieval_enabled=False)).ask({"question": q})
    assert response["status"] == "answered" and len(r.calls) == 1
    assert not response["diagnostics"]["multi_query"]
    assert "english_query" not in validate_plan(original_plan(q), q)


def test_english_rewrite_cannot_discard_original_chinese_branch():
    q = "模型如何处理长文本？"
    plan = {**original_plan(q), "rewritten_query": "Long text models", "english_query": "How do models process long texts?"}
    r = FakeRetriever([chunk("body", "Models process long texts.")])
    result = QAEngine(r, ScriptedMockLLM([plan, answer("body")]), {}).ask({"question": q})
    assert result["status"] == "answered"
    assert [c[0] for c in r.calls] == [q, plan["english_query"]]


def test_secondary_query_failure_preserves_primary_evidence():
    q = "如何处理长文本？"
    plan = {**original_plan(q), "english_query": "How to process long texts?"}
    class FailingEnglish(FakeRetriever):
        def search(self, query, **kwargs):
            if query == plan["english_query"]:
                raise ProjectError("EMBEDDING_UNAVAILABLE", "private upstream body")
            return [hit(chunk("body", "长文本可以作为上下文输入。"))]
    r = QAEngine(FailingEnglish(), ScriptedMockLLM([plan, answer("body")]), {}).ask({"question": q})
    assert r["status"] == "answered" and r["diagnostics"]["secondary_query_error"] == "EMBEDDING_UNAVAILABLE"
    assert "private upstream" not in str(r)


def test_query_fusion_deduplicates_and_keeps_branch_scores():
    a, b = hit(chunk("a", "first")), hit(chunk("b", "second"), 2)
    second = copy.deepcopy(a)
    second["scores"].update(bm25=8, cosine=.7)
    second["matched_by"] = ["keyword", "vector"]
    result = fuse_queries([[a, b], [second]])
    assert len(result) == 2 and result[0]["chunk"]["chunk_id"] == "a"
    assert len(result[0]["query_matches"]) == 2
    assert result[0]["scores"]["cosine"] == .6  # No addition of incompatible raw scores.
    assert set(result[0]["matched_by"]) == {"keyword", "vector"}


def test_different_language_versions_cannot_be_fused():
    a = hit(chunk("a", "first"))
    b = hit(chunk("b", "second"), version="idx_new")
    with pytest.raises(ProjectError) as exc:
        fuse_queries([[a], [b]])
    assert exc.value.code == "INDEX_NOT_READY"


def test_reference_detection_does_not_penalize_inline_citations():
    ordinary = "Transformers use attention (Vaswani et al., 2017). The context window limits input length (Lewis et al., 2020)."
    references = "A. Author. 2020. Long contexts.\n\nB. Writer. 2021. Attention.\n\nC. Person. 2022. Models."
    assert not reference_features(ordinary)[0]
    assert reference_features(references)[0]
    tail_years = "A. Author. A context study, 2020. 7\n\nB. Writer. Another paper, 2021. 2\n\nC. Person. A third paper, 2022. 3, 4"
    assert reference_features(tail_years)[0]


def test_body_reranking_allows_same_paper_and_downranks_bibliography():
    refs = "A. Author. 2020. Context window.\n\nB. Writer. 2021. Context window.\n\nC. Person. 2022. Context window."
    hits = [hit(chunk("refs", refs), 1),
            hit(chunk("body", "A model processes long texts with attention and a context window."), 4),
            hit(chunk("next", "The context window contains input tokens and limits sequence length.", offset=500), 5),
            hit(chunk("other", "A search index retrieves documents.", doc="d_other"), 2)]
    p = {**original_plan("长文本"), "english_query": "How do models process long texts using a context window?"}
    settings = {**DEFAULTS, "max_evidence_chunks": 2}
    ranked = rerank(hits, "长文本", p, settings)
    assert ranked[0]["chunk"]["chunk_id"] != "refs"
    assert next(h for h in ranked if h["chunk"]["chunk_id"] == "refs")["local_rerank"]["reference_penalty"] > 0
    selected = select_evidence(ranked, "长文本", p, settings, ["Test system prompt"])
    assert {c["chunk_id"] for c in selected} == {"body", "next"}
    assert all(c["text"] == next(h["chunk"]["text"] for h in hits if h["chunk"]["chunk_id"] == c["chunk_id"]) for c in selected)


def make_retriever(tmp_path):
    from dlrag.retrieval import Retriever
    from dlrag.retrieval.embeddings import FakeHashEmbedding
    class CountingBackend(FakeHashEmbedding):
        calls = 0
        def encode(self, texts):
            self.calls += 1
            return super().encode(texts)
    backend = CountingBackend()
    config = dict(count_mode="character", tokenizer_name=None, tokenizer_revision=None,
                  max_tokens=400, overlap_tokens=50, max_chars=1200, overlap_chars=150)
    b = Retriever(str(tmp_path / "index"), backend, {"chunking_config": config})
    chunks = [chunk("one", "Transformer attention processes long texts."),
              chunk("two", "Context window continues on the next page.", page=2),
              chunk("three", "More tokens consume memory.", page=2, offset=500),
              chunk("other", "Another document.", doc="d_other")]
    b.build(chunks)
    return b, backend, chunks


def test_snapshot_neighbors_cross_pages_without_network_or_mutation(tmp_path):
    b, backend, chunks = make_retriever(tmp_path)
    version = b.get_manifest()["index_version"]
    before = backend.calls
    adjacent = b.get_neighbors("two", filters={"year_from": 2024, "topics": ["IR"]}, expected_index_version=version)
    assert [h["chunk"]["chunk_id"] for h in adjacent] == ["one", "three"]
    assert backend.calls == before and validate_hits(adjacent) == version
    adjacent[0]["chunk"]["text"] = "tampered"
    assert b.get_neighbors("two")[0]["chunk"]["text"] == chunks[0]["text"]
    assert b.get_neighbors("two", filters={"topics": ["missing"]}) == []
    with pytest.raises(Exception) as exc:
        b.get_neighbors("two", expected_index_version="stale")
    assert exc.value.code == "INDEX_NOT_READY"


def test_neighbors_not_in_retrieval_can_be_selected_and_cited(tmp_path):
    b, _, chunks = make_retriever(tmp_path)
    class OnlySeed:
        def search(self, *a, **k):
            return [hit(chunks[0], version=b.get_manifest()["index_version"])]
        def get_manifest(self):
            return b.get_manifest()
        def get_neighbors(self, *a, **k):
            return b.get_neighbors(*a, **k)
    q = "Transformer"
    llm = ScriptedMockLLM([original_plan(q), answer("two")])
    result = QAEngine(OnlySeed(), llm, {}).ask({"question": q})
    assert result["status"] == "answered" and result["evidence"][0]["pdf_page"] == 2
    assert result["evidence"][0]["quote"] == chunks[1]["text"]
    assert result["diagnostics"]["neighbor_lookups"] == 1
    assert result["diagnostics"]["input_budget_upper_bound"] <= DEFAULTS["context_budget_tokens"]


def test_neighborhood_version_change_rejects_request(tmp_path):
    b, _, chunks = make_retriever(tmp_path)
    old = b.get_manifest()["index_version"]
    class Switched:
        def search(self, *a, **k):
            b.build(chunks)
            return [hit(chunks[0], version=old)]
        def get_neighbors(self, *a, **k):
            return b.get_neighbors(*a, **k)
    llm = ScriptedMockLLM([original_plan("Transformer"), answer("one")])
    result = QAEngine(Switched(), llm, {}).ask({"question": "Transformer"})
    assert result["status"] == "error" and result["error"]["code"] == "INDEX_NOT_READY"
    assert len(llm.calls) == 1


def test_budget_still_reserves_model_output():
    c = chunk("large", "文" * 2500)
    llm = ScriptedMockLLM([answer("large")])
    result = QAEngine(FakeRetriever([c]), llm, dict(planning_enabled=False, context_budget_tokens=30000,
                                                 context_window_tokens=2000)).ask({"question": "问题"})
    assert result["status"] == "insufficient_evidence" and not llm.calls
