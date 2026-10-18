"""Real answer/citation checks with a directly supporting B-recorded chunk."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from dlrag.qa import QAEngine, SiliconFlowLLM
from dlrag.qa.evaluation import evaluate


class FixedSnapshot:
    def __init__(self, hit):
        self.hit = hit

    def get_manifest(self):
        return {"index_version": self.hit["index_version"]}

    def search(self, query, filters=None, mode="hybrid", top_k=20):
        return [copy.deepcopy(self.hit)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    source = Path("evaluation/retrieval/arxiv_trial/runs.jsonl")
    records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    hits = [hit for record in records for hit in record["hits"]]
    # A recorded abstract directly states the computational overhead. No new
    # reference text is generated, and it remains pending original-PDF review.
    hit = next(h for h in hits if "50 million" in h["chunk"]["text"] and "65 hours" in h["chunk"]["text"])
    q = dict(question_id="grounded_SBERT_dev", split="dev", category="exact",
             question="Sentence-BERT 论文摘要指出，使用 BERT 在一万句话中寻找最相似句对需要多少次推理和多长时间？",
             filters={}, expected_status="answered", usable_for_evaluation=False,
             annotation_status="AI_source_inspection_pending_A_PDF_review",
             reference_points=["约五千万次推理，约65小时；仅指该摘要举例"],
             relevant_doc_ids=[hit["chunk"]["doc_id"]], relevant_chunk_ids=[hit["chunk"]["chunk_id"]])
    out = Path(args.output_dir)
    llm = SiliconFlowLLM.from_env()
    engine = QAEngine(FixedSnapshot(hit), llm, {"max_output_tokens": llm.max_output_tokens,
        "context_window_tokens": llm.context_window_tokens})
    evaluate(engine, [q], out)
    (out / "api_calls.json").write_text(json.dumps(llm.records, indent=2), encoding="utf-8")
    (out / "source.json").write_text(json.dumps(dict(mode="real_llm_fixed_recorded_supporting_chunk",
        live_retrieval=False, source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        hit=hit), ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output_dir": str(out), "mode": "real_llm_fixed_recorded_supporting_chunk"}))


if __name__ == "__main__":
    main()
