"""围绕检索契约、过滤、快照与失败保留行为的离线测试。"""

import copy
import json
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from dlrag.retrieval import ProjectError, Retriever
from dlrag.retrieval.embeddings import FakeHashEmbedding
from dlrag.retrieval.fusion import reciprocal_rank_fusion
from dlrag.retrieval.lexical import tokenize

CONFIG = {"count_mode": "character", "tokenizer_name": None, "tokenizer_revision": None,
          "max_tokens": 400, "overlap_tokens": 50, "max_chars": 1200, "overlap_chars": 150}


def chunk(cid, text, year=2024, topics=None, doc_id=None):
    return {"chunk_id": cid, "doc_id": doc_id or "d_" + cid, "pdf_page": 1,
            "printed_page": None, "section": None, "text": text,
            "page_char_start": 0, "page_char_end": len(text), "token_count": None,
            "document": {"title": "合成测试资料", "authors": [], "year": year,
                         "topics": ["IR"] if topics is None else topics, "language": "mixed"}}


class ControlledEmbedding:
    model = "fake-controlled"
    revision = "1"
    dimension = 2

    def __init__(self):
        self.fail = False
        self.values = {"BM25 exact": [1, 0], "different wording": [0.8, 0.6],
                       "unrelated": [0, 1], "semantic query": [1, 0]}

    def encode(self, texts):
        if self.fail:
            raise RuntimeError("受控测试故障")
        return np.asarray([self.values.get(text, [1, 0]) for text in texts], dtype=np.float32)


@pytest.fixture
def sample():
    return [chunk("c_a", "BM25 exact", 2024, ["IR"]),
            chunk("c_b", "different wording", 2020, ["DL"]),
            chunk("c_c", "unrelated", None, ["IR", "DL"])]


def make(tmp_path, backend=None, **settings):
    return Retriever(str(tmp_path / "indexes"), backend or ControlledEmbedding(),
                     {"chunking_config": CONFIG, **settings})


def test_keyword_vector_and_return_contract(tmp_path, sample):
    retriever = make(tmp_path)
    manifest = retriever.build(sample)
    keyword = retriever.search("bm25", mode="keyword")
    assert [h["chunk"]["chunk_id"] for h in keyword] == ["c_a"]
    assert keyword[0]["scores"]["cosine"] is None
    vector = retriever.search("semantic query", mode="vector")
    assert [h["chunk"]["chunk_id"] for h in vector] == ["c_a", "c_b", "c_c"]
    assert vector[0]["scores"]["cosine"] == pytest.approx(1)
    assert vector[1]["scores"]["cosine"] == pytest.approx(0.8)
    assert vector[0]["scores"]["bm25"] is None
    assert all(h["scores"]["rrf"] is None and h["scores"]["rerank"] is None for h in vector)
    assert all(h["index_version"] == manifest["index_version"] for h in vector)
    assert manifest["tokenizer"] is None and manifest["chunking_config"] == CONFIG
    assert [h["rank"] for h in vector] == [1, 2, 3]
    vector[0]["chunk"]["text"] = "修改外部结果"
    manifest["dimension"] = 0
    assert retriever.search("semantic query", mode="vector")[0]["chunk"]["text"] == "BM25 exact"
    assert retriever.get_manifest()["dimension"] == 2


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid"])
def test_filter_before_ranking_inclusive_years_unknown_year_topics(tmp_path, mode):
    backend = ControlledEmbedding()
    sample = [chunk("c_a", "BM25 exact", 2024, ["IR"]),
              chunk("c_b", "BM25 exact eligible", 2020, ["DL"]),
              chunk("c_c", "BM25 exact unknown", None, ["DL"])]
    backend.values["BM25 exact eligible"] = [0.8, 0.6]
    backend.values["BM25 exact unknown"] = [0, 1]
    retriever = make(tmp_path, backend, candidate_k=1)
    retriever.build(sample)
    hits = retriever.search("BM25", {"year_from": 2020, "year_to": 2020, "topics": ["DL", "other"]}, mode, top_k=1)
    assert [h["chunk"]["chunk_id"] for h in hits] == ["c_b"]
    assert retriever.search("BM25", {"topics": ["missing"]}, mode) == []


def test_rrf_hand_computation_and_branch_membership(tmp_path, sample):
    result = reciprocal_rank_fusion([["a", "b"], ["b", "c"]], 60)
    assert result["a"] == pytest.approx(1 / 61)
    assert result["b"] == pytest.approx(1 / 62 + 1 / 61)
    retriever = make(tmp_path)
    retriever.build(sample)
    hits = retriever.search("BM25", mode="hybrid")
    assert hits[0]["matched_by"] == ["keyword", "vector"]
    assert hits[0]["scores"]["rrf"] == pytest.approx(2 / 61)
    assert len({h["chunk"]["chunk_id"] for h in hits}) == len(hits)
    assert hits[1]["matched_by"] == ["vector"]


def test_top_k_expands_branch_and_ties_stable(tmp_path):
    retriever = make(tmp_path, candidate_k=2)
    retriever.build([chunk(f"c_{i:03d}", "BM25 exact") for i in range(60)])
    for mode in ("keyword", "vector", "hybrid"):
        hits = retriever.search("BM25", mode=mode, top_k=50)
        assert len(hits) == 50
        assert [h["chunk"]["chunk_id"] for h in hits] == [f"c_{i:03d}" for i in range(50)]


def test_save_reload_without_network_and_metadata_hash(tmp_path, sample):
    backend = ControlledEmbedding()
    retriever = make(tmp_path, backend)
    first = retriever.build(sample)
    before = retriever.search("BM25", mode="hybrid")
    backend.fail = True
    loaded = make(tmp_path, backend)
    assert loaded.load() == first  # 加载不调用嵌入服务。
    assert loaded.search("BM25", mode="keyword")
    backend.fail = False
    assert loaded.search("BM25", mode="hybrid") == before
    changed = copy.deepcopy(sample)
    changed[0]["document"]["year"] = 2023
    second = retriever.build(changed)
    assert first["corpus_hash"] != second["corpus_hash"]
    assert (tmp_path / "indexes" / first["index_version"]).is_dir()
    assert make(tmp_path).load()["index_version"] == second["index_version"]


def test_failed_embedding_build_preserves_disk_and_memory(tmp_path, sample):
    backend = ControlledEmbedding()
    retriever = make(tmp_path, backend)
    previous = retriever.build(sample)
    before = retriever.search("BM25", mode="keyword")
    backend.fail = True
    with pytest.raises(ProjectError):
        retriever.build(sample)
    assert retriever.get_manifest() == previous
    assert retriever.search("BM25", mode="keyword") == before
    assert make(tmp_path, backend).load() == previous
    assert not list((tmp_path / "indexes").glob(".building_*"))


def test_failed_pointer_switch_preserves_active_version(tmp_path, sample, monkeypatch):
    import dlrag.retrieval.retriever as module
    retriever = make(tmp_path)
    previous = retriever.build(sample)
    real_replace = module.os.replace
    def fail_pointer(source, target):
        if target.name == "current.json":
            raise OSError("模拟指针写入失败")
        return real_replace(source, target)
    monkeypatch.setattr(module.os, "replace", fail_pointer)
    with pytest.raises(ProjectError) as error:
        retriever.build(sample)
    assert error.value.code == "INDEX_BUILD_FAILED"
    assert retriever.get_manifest() == previous
    assert make(tmp_path).load() == previous


@pytest.mark.parametrize("change", ["model", "dimension", "normalization", "chunking", "lexical"])
def test_incompatible_load_rejected(tmp_path, sample, change):
    retriever = make(tmp_path)
    retriever.build(sample)
    backend = ControlledEmbedding()
    settings = {}
    if change == "model": backend.model = "wrong"
    if change == "dimension": backend.dimension = 3
    if change == "normalization": settings["normalize_embeddings"] = False
    if change == "chunking": settings["chunking_config"] = {**CONFIG, "max_chars": 1000}
    if change == "lexical": settings["bm25_b"] = 0.5
    with pytest.raises(ProjectError) as error:
        make(tmp_path, backend, **settings).load()
    assert error.value.code == "EMBEDDING_MISMATCH"


def test_corruption_and_path_rejected_keep_loaded_snapshot(tmp_path, sample):
    retriever = make(tmp_path)
    manifest = retriever.build(sample)
    path = tmp_path / "indexes" / manifest["index_version"] / "chunks.json"
    path.write_text("[]")
    with pytest.raises(ProjectError): retriever.load()
    assert retriever.search("BM25", mode="keyword")
    (tmp_path / "indexes" / "current.json").write_text(json.dumps({"index_version": "../outside"}))
    with pytest.raises(ProjectError): make(tmp_path).load()


def test_empty_library_has_manifest_and_does_not_call_embedding(tmp_path):
    backend = ControlledEmbedding()
    backend.fail = True
    retriever = make(tmp_path, backend)
    manifest = retriever.build([])
    assert manifest["chunk_count"] == 0 and manifest["document_count"] == 0
    for mode in ("keyword", "vector", "hybrid"):
        assert retriever.search("查询", mode=mode) == []
    assert make(tmp_path, backend).load() == manifest


@pytest.mark.parametrize("vectors", [[[0, 0]], [[float("nan"), 1]], [[float("inf"), 1]], [[1, 0, 0]]])
def test_bad_vectors_rejected(tmp_path, vectors):
    backend = ControlledEmbedding()
    backend.encode = lambda texts: vectors
    with pytest.raises(ProjectError): make(tmp_path, backend).build([chunk("c_a", "body")])


def test_cosine_when_normalization_disabled(tmp_path, sample):
    retriever = make(tmp_path, normalize_embeddings=False)
    retriever.build(sample)
    hits = retriever.search("semantic query", mode="vector")
    assert hits[0]["scores"]["cosine"] == pytest.approx(1)
    assert hits[1]["scores"]["cosine"] == pytest.approx(0.8)
    assert make(tmp_path, normalize_embeddings=False).load()["normalized"] is False


@pytest.mark.parametrize("kwargs", [{"query": " "}, {"query": "x" * 2001}, {"query": "q", "top_k": 0},
    {"query": "q", "top_k": 51}, {"query": "q", "top_k": True}, {"query": "q", "mode": "other"},
    {"query": "q", "filters": {"year_from": 2025, "year_to": 2020}},
    {"query": "q", "filters": {"year_from": True}}, {"query": "q", "filters": {"topics": "IR"}},
    {"query": "q", "filters": {"language": "en"}}])
def test_invalid_requests(tmp_path, kwargs):
    with pytest.raises(ProjectError) as error: make(tmp_path).search(**kwargs)
    assert error.value.code == "INVALID_REQUEST"


def test_missing_index_duplicate_ids_offsets_and_configuration(tmp_path, sample):
    with pytest.raises(ProjectError): make(tmp_path).search("q")
    with pytest.raises(ProjectError): make(tmp_path).load()
    for chunks in ([sample[0], sample[0]], [{**sample[0], "page_char_end": 1}]):
        with pytest.raises(ProjectError): make(tmp_path).build(chunks)
    with pytest.raises(ProjectError): Retriever(str(tmp_path), ControlledEmbedding(), {}).build(sample)


def test_chinese_english_tokenization_and_overlapping_evidence(tmp_path):
    assert tokenize("BM25 BGE-M3 ｒｒｆ") == ["bm25", "bge-m3", "rrf"]
    assert "检索" in tokenize("语义检索")
    retriever = make(tmp_path, FakeHashEmbedding())
    retriever.build([chunk("c_a", "中文语义检索证据"), chunk("c_b", "中文语义检索证据还有另一要点")])
    assert len(retriever.search("语义检索", mode="keyword")) == 2


def test_generic_chinese_topic_does_not_create_single_character_hits(tmp_path):
    retriever = make(tmp_path, FakeHashEmbedding())
    paper = chunk("c_a", "An English paper.", topics=["arXiv实验"])
    paper["document"]["title"] = "An English paper"
    retriever.build([paper])
    assert retriever.search("找真实资料", mode="keyword") == []


def test_concurrent_reads_have_one_complete_snapshot(tmp_path, sample):
    retriever = make(tmp_path)
    retriever.build(sample)
    def query(_):
        hits = retriever.search("BM25", mode="hybrid")
        assert len({h["index_version"] for h in hits}) == 1
        return hits
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(query, range(10)))
    assert all(result == results[0] for result in results)
