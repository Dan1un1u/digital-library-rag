import copy
import pytest

from dlrag.qa import QAEngine, ScriptedMockLLM, ProjectError
from dlrag.qa.demo import FakeRetriever, demo_outputs
from dlrag.qa.validation import validate_answer
from dlrag.shared.models import AnswerResponse


def output():
    value = demo_outputs("BM25", "answered")[1]
    value["claims"].append(copy.deepcopy(value["claims"][0]))
    value["sections"] = [{"heading": "", "claim_indices": [1, 2]}]
    return value


def test_paragraphs_use_validated_claims_with_no_extra_call():
    plan = demo_outputs("BM25", "answered")[0]
    llm = ScriptedMockLLM([plan, output()])
    stages = []
    answer = QAEngine(FakeRetriever(), llm, {}).ask_with_progress({"question": "BM25"}, stages.append)
    assert answer["status"] == "answered"
    assert answer["answer_sections"] == [{"heading": "", "claim_ids": ["cl_1", "cl_2"]}]
    assert len(llm.calls) == 2
    assert stages == ["planning", "retrieval", "evidence_selection", "generation", "validation"]
    AnswerResponse.model_validate(answer)


@pytest.mark.parametrize("indices", [[0, 1], [1, 1], [1], [True, 2], [1, 2, 3]])
def test_bad_paragraph_refs_rejected(indices):
    value = output()
    value["sections"][0]["claim_indices"] = indices
    with pytest.raises(ProjectError):
        validate_answer(value, FakeRetriever().chunks)


def test_progress_observer_failure_does_not_break_answer():
    def broken(stage):
        raise RuntimeError("disconnected")
    result = QAEngine(FakeRetriever(), ScriptedMockLLM(demo_outputs("BM25", "answered")), {}).ask_with_progress(
        {"question": "BM25"}, broken)
    assert result["status"] == "answered"


def test_invalid_sections_repair_in_existing_bounded_attempt():
    bad = output()
    bad["sections"][0]["claim_indices"] = [9]
    llm = ScriptedMockLLM([demo_outputs("BM25", "answered")[0], bad, output()])
    stages = []
    result = QAEngine(FakeRetriever(), llm, {}).ask_with_progress({"question": "BM25"}, stages.append)
    assert result["status"] == "answered" and len(llm.calls) == 3
    assert stages[-2:] == ["repair", "validation"]


def test_public_paragraphs_cannot_reference_missing_claim():
    answer = QAEngine(FakeRetriever(), ScriptedMockLLM(demo_outputs("BM25", "answered")), {}).ask({"question": "BM25"})
    answer["answer_sections"][0]["claim_ids"] = ["made_up"]
    with pytest.raises(ValueError):
        AnswerResponse.model_validate(answer)
