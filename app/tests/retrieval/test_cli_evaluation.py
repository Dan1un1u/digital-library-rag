"""独立命令及未经复核标注的评估处理。"""

import json
import csv
import subprocess
import sys

import pytest

from dlrag.retrieval import ProjectError, Retriever
from dlrag.retrieval.cli import synthetic_chunks
from dlrag.retrieval.embeddings import FakeHashEmbedding
from dlrag.retrieval.evaluation import evaluate

CONFIG = {"count_mode": "character", "tokenizer_name": None, "tokenizer_revision": None,
          "max_tokens": 400, "overlap_tokens": 50, "max_chars": 1200, "overlap_chars": 150}


def test_independent_demo_reload_and_input_error(tmp_path):
    command = [sys.executable, "-m", "dlrag.retrieval.cli"]
    common = ["--index-dir", str(tmp_path / "indexes"), "--backend", "fake"]
    demo = subprocess.run(command + ["demo"] + common, capture_output=True, text=True)
    assert demo.returncode == 0, demo.stderr
    result = json.loads(demo.stdout)
    assert result["mode"] == "fake" and result["manifest"]["chunk_count"] == 10
    queried = subprocess.run(command + ["search"] + common + ["--query", "BM25", "--mode", "keyword"], capture_output=True, text=True)
    assert queried.returncode == 0 and json.loads(queried.stdout)["hits"]
    bad = subprocess.run(command + ["search"] + common + ["--query", " "], capture_output=True, text=True)
    assert bad.returncode == 1 and json.loads(bad.stderr)["error"]["code"] == "INVALID_REQUEST"


def test_unreviewed_questions_and_fake_do_not_produce_quality_scores(tmp_path):
    retriever = Retriever(str(tmp_path / "indexes"), FakeHashEmbedding(), {"chunking_config": CONFIG})
    retriever.build(synthetic_chunks())
    questions = [{"question_id": "pending", "question": "BM25", "split": "dev",
                  "expected_status": "answered", "relevant_chunk_ids": ["c_synthetic_01"],
                  "usable_for_evaluation": False},
                 {"question_id": "fake", "question": "BM25", "split": "dev",
                  "expected_status": "answered", "relevant_chunk_ids": ["c_synthetic_01"]}]
    summary = evaluate(retriever, questions, tmp_path / "evaluation")
    assert all(row["hit_at_5"] is None and row["scored_questions"] == 0 for row in summary["metrics"])
    assert len((tmp_path / "evaluation/runs.jsonl").read_text().splitlines()) == 6


def test_metrics_from_explicit_labels_and_evidence_groups(tmp_path):
    backend = FakeHashEmbedding()
    backend.model = "controlled-labelled-test"
    backend.get_config = lambda: {"provider": "controlled-test", "model": backend.model,
                                  "revision": "1", "dimension": backend.dimension}
    retriever = Retriever(str(tmp_path / "indexes"), backend, {"chunking_config": CONFIG})
    retriever.build(synthetic_chunks())
    question = {"question_id": "labelled", "question": "BM25", "split": "dev",
                "expected_status": "answered", "relevant_chunk_ids": ["c_synthetic_01"],
                "evidence_groups": [["c_synthetic_01"]]}
    summary = evaluate(retriever, [question], tmp_path / "evaluation")
    keyword = summary["metrics"][0]
    assert keyword["hit_at_5"] == keyword["recall_at_5"] == keyword["recall_at_10"] == 1
    assert keyword["evidence_group_coverage_at_10"] == 1


class LabelledRetriever:
    """固定排名，隔离集合汇总逻辑；不使用网络或语义模型。"""
    def __init__(self):
        self.calls = []

    def get_manifest(self):
        return {"index_version": "controlled", "embedding_model": "controlled-test",
                "embedding_backend": {"provider": "controlled-test"}}

    def get_chunk_ids(self):
        return {"relevant", "other"}

    def search(self, query, filters, mode, top_k):
        self.calls.append((query, mode, top_k))
        ranking = ["relevant"] if query == "dev hit" else ["other"]
        if query == "recall cutoff":
            ranking = ["other", "relevant"]
        return [{"chunk": {"chunk_id": cid}, "index_version": "controlled"}
                for cid in ranking[:top_k]]


def labelled_question(identifier, split, query):
    return {"question_id": identifier, "split": split, "question": query,
            "expected_status": "answered", "relevant_chunk_ids": ["relevant"],
            "evidence_groups": [["relevant"]]}


def test_dev_test_metrics_and_csv_are_separate(tmp_path):
    questions = [labelled_question("dev", "dev", "dev hit"),
                 labelled_question("test", "test", "test miss")]
    summary = evaluate(LabelledRetriever(), questions, tmp_path)
    assert summary["metric_grouping"] == ["split", "mode"]
    assert summary["question_counts_by_split"] == {"dev": 1, "test": 1}
    assert len(summary["metrics"]) == 6
    for mode in ("keyword", "vector", "hybrid"):
        rows = {row["split"]: row for row in summary["metrics"] if row["mode"] == mode}
        for metric in ("hit_at_5", "recall_at_5", "recall_at_10", "evidence_group_coverage_at_10"):
            assert rows["dev"][metric] == 1
            assert rows["test"][metric] == 0
        assert rows["dev"]["questions"] == rows["test"]["questions"] == 1
        assert rows["dev"]["scored_questions"] == rows["test"]["scored_questions"] == 1
    persisted = json.loads((tmp_path / "summary.json").read_text())
    assert persisted["metrics"] == summary["metrics"]
    with (tmp_path / "metrics.csv").open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 6
    assert all(float(row["hit_at_5"]) == (1 if row["split"] == "dev" else 0) for row in rows)


@pytest.mark.parametrize("top_k", [0, 1, 9, 51, True, 10.5, "10", None])
def test_direct_evaluation_rejects_invalid_recall_cutoff_before_search(tmp_path, top_k):
    retriever = LabelledRetriever()
    question = labelled_question("cutoff", "test", "recall cutoff")
    output = tmp_path / "not_created"
    with pytest.raises(ProjectError) as error:
        evaluate(retriever, [question], output, top_k=top_k)
    assert error.value.code == "INVALID_REQUEST"
    assert retriever.calls == [] and not output.exists()


def test_direct_evaluation_recall_at_10_uses_at_least_ten_candidates(tmp_path):
    question = labelled_question("cutoff", "test", "recall cutoff")
    summary = evaluate(LabelledRetriever(), [question], tmp_path, top_k=10)
    assert all(row["recall_at_10"] == 1 for row in summary["metrics"])


def test_direct_evaluation_rejects_unknown_split(tmp_path):
    with pytest.raises(ProjectError) as error:
        evaluate(LabelledRetriever(), [labelled_question("invalid", "unknown", "dev hit")], tmp_path)
    assert error.value.code == "INVALID_REQUEST"


def test_empty_evaluation_writes_headers_without_inventing_metrics(tmp_path):
    summary = evaluate(LabelledRetriever(), [], tmp_path)
    assert summary["metrics"] == []
    assert summary["question_counts_by_split"] == {"dev": 0, "test": 0}
    assert (tmp_path / "metrics.csv").read_text(encoding="utf-8-sig").startswith("split,mode,")
    assert (tmp_path / "runs.jsonl").read_text() == ""
