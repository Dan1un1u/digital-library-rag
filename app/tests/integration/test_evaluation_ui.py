import copy
import json
from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from scripts.run_evaluation import collect, evaluate, percentiles, validate_dataset
from dlrag.ui.client import citation_numbers, clarified_question


def test_provenance_uses_current_source_hash():
    from scripts.run_evaluation import source_snapshot
    snapshot = source_snapshot()
    import hashlib
    root = Path(__file__).parents[2]
    assert snapshot["files"]["src/dlrag/api/qa_factory.py"] == hashlib.sha256((root / "src/dlrag/api/qa_factory.py").read_bytes()).hexdigest()
    assert len(snapshot["sha256"]) == 64


def row(question="BM25", qid="d001", split="dev"):
    return {"question_id": qid, "question": question, "split": split, "category": "exact",
            "filters": {}, "expected_status": "answered", "relevant_chunk_ids": [],
            "evidence_groups": [], "usable_for_evaluation": False}


def test_real_rejects_unreviewed_dataset(services):
    with pytest.raises(ValueError, match="未复核"):
        validate_dataset([row()], services, "real")


def test_split_leakage_and_duplicate(services):
    a, b = row(), row("BM25 怎么用", "d002", "test")
    a["paraphrase_group"] = b["paraphrase_group"] = "same"
    with pytest.raises(ValueError, match="dev/test"):
        validate_dataset([a, b], services, "mock")
    with pytest.raises(ValueError, match="ID 重复"):
        validate_dataset([a, a], services, "mock")


def test_mock_scores_are_null_and_failures_separate(imported, services, tmp_path):
    rows = [row(), {**row("超时", "d002", "test"), "expected_status": "answered"}]
    result = evaluate(rows, services, "mock", "hybrid", tmp_path / "run")
    assert result["mock_scores_excluded"] is True and result["by_split"]["test"]["failures"] == 1
    assert result["by_split"]["dev"]["metrics"]["hit_at_5"] == {"value": None, "denominator": 0}
    assert result["human_metrics_status"] == "未评估"
    assert result["by_split"]["dev"]["timings"]["sample_count"] == 1
    assert percentiles([])["median_ms"] is None
    assert evaluate([], services, "mock", "keyword", tmp_path / "empty")["empty_dataset"] is True


def test_collect_marks_templates_and_missing_roles(tmp_path):
    folder = tmp_path / "handoff/D"
    folder.mkdir(parents=True)
    (folder / "candidate_questions.jsonl").write_text(json.dumps(row()), encoding="utf-8")
    result = collect(tmp_path, tmp_path / "questions.jsonl")
    assert result["missing_roles"] == ["A", "B", "C"]
    assert json.loads((tmp_path / "questions.jsonl").read_text(encoding="utf-8"))["usable_for_evaluation"] is False


def test_ui_citations_and_clarification():
    assert citation_numbers({"evidence": [{"evidence_id": "ev_3"}, {"evidence_id": "ev_1"}]}) == {"ev_3": 1, "ev_1": 2}
    assert clarified_question("原问题", "选项") == "原问题\n补充选择：选项"


def test_streamlit_pages_and_question_citation(client, imported, monkeypatch):
    def local_api(base, method, path, **kwargs):
        return client.request(method, path, **kwargs).json()
    monkeypatch.setattr("dlrag.ui.client.call_api", local_api)
    path = str(Path(__file__).parents[2] / "src/dlrag/ui/app.py")
    app = AppTest.from_file(path, default_timeout=20).run()
    assert not app.exception
    assert not any("MOCK" in warning.value for warning in app.warning)
    app.sidebar.radio[0].set_value("搜索与问答").run()
    app.text_area[0].set_value("BM25")
    next(widget for widget in app.radio if widget.label == "操作").set_value("问答")
    next(widget for widget in app.button if widget.label == "提交").click().run()
    assert not app.exception
    assert any("查看原文" in button.label for button in app.button)
    assert any('<sup><a href=' in item.value and '/sources/' in item.value for item in app.markdown)
    assert not any("是否有帮助" in widget.label for widget in app.radio)
    assert not any(button.label == "保存反馈" for button in app.button)
    next(button for button in app.button if "查看原文" in button.label).click().run()
    assert app.session_state["selected_evidence"] == "ev_1"
    app.sidebar.radio[0].set_value("上传与管理").run()
    assert not app.exception
