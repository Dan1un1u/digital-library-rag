"""Real LLM on B's recorded hit snapshots, NOT live retrieval."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from dlrag.qa import QAEngine, SiliconFlowLLM
from dlrag.qa.evaluation import evaluate


class RecordedRetriever:
    def __init__(self):
        self.active = None

    def get_manifest(self):
        return {"index_version": self.active["index_version"]} if self.active else None

    def search(self, query, filters=None, mode="hybrid", top_k=20):
        # Fixed candidate pool: no rewrite retrieval gains or filtering claimed.
        return copy.deepcopy(self.active["hits"][:top_k])


class ReplayEngine:
    def __init__(self, engine, by_question):
        self.engine, self.by_question = engine, by_question
        self.llm, self.settings = engine.llm, engine.settings

    def ask(self, request):
        self.engine.retriever.active = self.by_question[request["question"]]
        result = self.engine.ask(request)
        result["diagnostics"]["retrieval_source"] = "B_recorded_hybrid_hits_not_live_search"
        return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    source = Path("evaluation/retrieval/arxiv_trial/runs.jsonl")
    records = [json.loads(x) for x in source.read_text(encoding="utf-8").splitlines()]
    records = {r["question_id"]: r for r in records if r["mode"] == "hybrid"}
    candidates = [json.loads(x) for x in Path("handoff/C/candidate_questions.jsonl").read_text(encoding="utf-8").splitlines()]
    questions, by_question = [], {}
    for key in ("B001", "B002"):
        record = records[key]
        q = dict(question_id="smoke_" + key, split="dev", category="vague", question=record["query"],
                 filters=record["filters"], expected_status="answered", usable_for_evaluation=False,
                 annotation_status="B_AI_draft_pending_human_review", reference_points=[])
        questions.append(q)
        by_question[q["question"]] = record
    for key in ("C001", "C011"):
        q = next(c for c in candidates if c["question_id"] == key)
        questions.append(q)
        by_question[q["question"]] = records["B001"]
    output = Path(args.output_dir)
    if output.exists() and any(output.iterdir()):
        parser.error("output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    for baseline in (False, True):
        llm = SiliconFlowLLM.from_env()
        engine = QAEngine(RecordedRetriever(), llm, dict(planning_enabled=not baseline,
            max_output_tokens=llm.max_output_tokens, context_window_tokens=llm.context_window_tokens))
        variant = "baseline" if baseline else "full"
        evaluate(ReplayEngine(engine, by_question), questions, output / variant, variant)
        (output / variant / "api_calls.json").write_text(json.dumps(llm.records, indent=2), encoding="utf-8")
    (output / "source.json").write_text(json.dumps(dict(
        source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        mode="real_llm_recorded_retrieval", live_retrieval=False,
        uploaded_content="each question and selected recorded text chunks only",
        quality_metrics="not_scored_pending_human_review", model_config=llm.get_config()), indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(output), "mode": "real_llm_recorded_retrieval", "questions_per_variant": len(questions)}))


if __name__ == "__main__":
    main()
