import csv
import json
import pytest
from dlrag.qa import QAEngine, ProjectError, ScriptedMockLLM
from dlrag.qa.demo import FakeRetriever, demo_outputs
from dlrag.qa.evaluation import evaluate, summarize_review


def test_runs_reviews_and_no_fake_semantic_scores(tmp_path):
    q = "BM25 是什么？"
    questions = [dict(question_id="C01", split="dev", question=q, expected_status="answered", usable_for_evaluation=False)]
    engine = QAEngine(FakeRetriever(), ScriptedMockLLM(demo_outputs(q, "answered")), {})
    manifest = evaluate(engine, questions, tmp_path / "run")
    assert manifest["count"] == 1
    rows = list(csv.DictReader((tmp_path / "run/metrics.csv").open(encoding="utf-8-sig")))
    assert rows[0]["citation_support_accuracy"] == "" and rows[0]["reviewed_eligible_count"] == "0"
    review = list(csv.DictReader((tmp_path / "run/review_template.csv").open(encoding="utf-8-sig")))
    assert review[0]["quote"] and not review[0]["reviewer"]
    run = json.loads((tmp_path / "run/runs.jsonl").read_text(encoding="utf-8"))
    assert run["response"]["diagnostics"]["selected_chunk_ids"]
    with pytest.raises(ProjectError):
        evaluate(engine, questions, tmp_path / "run")
    assert summarize_review(tmp_path / "run", tmp_path / "run/review_template.csv", tmp_path / "grades.csv") == []


def test_real_human_review_is_required_and_aggregated(tmp_path):
    q = "BM25 是什么？"
    class MarkedReal(ScriptedMockLLM):
        # Only tests the aggregator gate; never reported as actual model results.
        def get_config(self):
            return {"mode": "real"}
    engine = QAEngine(FakeRetriever(), MarkedReal(demo_outputs(q, "answered")), {})
    questions = [dict(question_id="C01", split="test", question=q, expected_status="answered", usable_for_evaluation=True)]
    evaluate(engine, questions, tmp_path / "run")
    path = tmp_path / "run/review_template.csv"
    with pytest.raises(ProjectError):
        summarize_review(tmp_path / "run", path, tmp_path / "grades.csv")
    rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
    rows[0].update(reviewer="test reviewer", support="unsupported", point_score="0", point_max="1", coverage="0")
    from dlrag.qa.evaluation import write_csv, REVIEW_FIELDS
    write_csv(path, REVIEW_FIELDS, rows)
    grades = summarize_review(tmp_path / "run", path, tmp_path / "grades.csv")
    assert grades[0]["citation_support_accuracy"] == 0 and grades[0]["answer_point_score"] == 0
