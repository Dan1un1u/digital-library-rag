"""三种检索对比；没有复核标注时不输出质量成绩。"""

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .errors import ProjectError

METRIC_FIELDS = ["split", "mode", "questions", "scored_questions", "hit_at_5",
                 "recall_at_5", "recall_at_10", "evidence_group_coverage_at_10",
                 "median_ms", "p95_ms"]


def validate_questions(questions):
    if not isinstance(questions, list):
        raise ProjectError("INVALID_REQUEST", "评估题目必须是列表")
    identifiers = set()
    for question in questions:
        if (not isinstance(question, dict) or not isinstance(question.get("question_id"), str)
                or not question["question_id"].strip() or question["question_id"] in identifiers
                or not isinstance(question.get("question"), str) or not question["question"].strip()
                or question.get("split") not in ("dev", "test")):
            raise ProjectError("INVALID_REQUEST", "评估题目缺少标识、问题、集合划分，或标识重复")
        identifiers.add(question["question_id"])


def read_questions(path):
    questions = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        questions.append(json.loads(line))
    validate_questions(questions)
    return questions


def summarize_runs(runs):
    """由逐题记录按集合和模式汇总，也用于重新汇总既有真实实验。"""
    rows = []
    for mode in ("keyword", "vector", "hybrid"):
        for split in ("dev", "test"):
            grouped = [run for run in runs if run["split"] == split and run["mode"] == mode]
            if not grouped:
                continue
            scored = [run for run in grouped if run["quality_metrics"]["hit_at_5"] is not None]
            metrics = {}
            for name in ("hit_at_5", "recall_at_5", "recall_at_10", "evidence_group_coverage_at_10"):
                values = [run["quality_metrics"][name] for run in scored
                          if run["quality_metrics"][name] is not None]
                metrics[name] = float(np.mean(values)) if values else None
            latencies = [run["elapsed_ms"] for run in grouped]
            rows.append({"split": split, "mode": mode, "questions": len(grouped),
                         "scored_questions": len(scored), **metrics,
                         "median_ms": float(np.median(latencies)),
                         "p95_ms": float(np.percentile(latencies, 95))})
    return rows


def evaluate(retriever, questions, output, top_k=20):
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 10 <= top_k <= 50:
        raise ProjectError("INVALID_REQUEST", "评估 Recall@10 须设置整数 top_k，范围为 10–50")
    validate_questions(questions)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    manifest = retriever.get_manifest()
    if manifest is None:
        raise ProjectError("INDEX_NOT_READY", "评估须先加载索引")
    fake = manifest["embedding_backend"].get("provider") == "fake" or manifest["embedding_model"].startswith("fake")
    valid_ids = retriever.get_chunk_ids()
    runs = []
    for mode in ("keyword", "vector", "hybrid"):
        for question in questions:
            start = time.perf_counter()
            hits = retriever.search(question["question"], question.get("filters"), mode, top_k)
            if retriever.get_manifest()["index_version"] != manifest["index_version"]:
                raise ProjectError("INDEX_NOT_READY", "评估期间有效索引发生变化，请冻结索引后重跑")
            elapsed = (time.perf_counter() - start) * 1000
            labels = question.get("relevant_chunk_ids", [])
            groups = question.get("evidence_groups", [])
            if not isinstance(labels, list) or any(not isinstance(v, str) for v in labels):
                raise ProjectError("INVALID_REQUEST", "相关片段标注必须是字符串列表")
            if not isinstance(groups, list) or any(not isinstance(g, list) or not g or any(not isinstance(v, str) for v in g) for g in groups):
                raise ProjectError("INVALID_REQUEST", "证据组须为非空片段编号列表组成的列表")
            if set(labels) - valid_ids or any(set(group) - valid_ids for group in groups):
                raise ProjectError("INVALID_REQUEST", "评估标注引用了当前索引中不存在的片段")
            explicitly_excluded = question.get("usable_for_evaluation") is False
            scoreable = (not fake and not explicitly_excluded and bool(labels)
                         and question.get("expected_status") == "answered")
            per_question = {"hit_at_5": None, "recall_at_5": None, "recall_at_10": None,
                            "evidence_group_coverage_at_10": None}
            if scoreable:
                # 编号存在只是标注结构校验，不能替代人工支持关系核验。
                relevant = set(labels)
                top5 = {h["chunk"]["chunk_id"] for h in hits[:5]}
                top10 = {h["chunk"]["chunk_id"] for h in hits[:10]}
                per_question.update(hit_at_5=int(bool(relevant & top5)),
                                    recall_at_5=len(relevant & top5) / len(relevant),
                                    recall_at_10=len(relevant & top10) / len(relevant))
                if groups:
                    per_question["evidence_group_coverage_at_10"] = sum(bool(set(g) & top10) for g in groups) / len(groups)
            run = {"question_id": question["question_id"], "split": question["split"],
                   "query": question["question"], "filters": question.get("filters", {}),
                   "mode": mode, "index_version": manifest["index_version"],
                   "elapsed_ms": round(elapsed, 3), "hits": hits,
                   "quality_metrics": per_question,
                   "quality_metrics_status": "computed_from_supplied_labels" if scoreable else "not_computed_unreviewed_or_missing_labels_or_fake",
                   "annotation_status": question.get("annotation_status")}
            runs.append(run)
    rows = summarize_runs(runs)
    with (output / "runs.jsonl").open("w", encoding="utf-8") as stream:
        for run in runs:
            stream.write(json.dumps(run, ensure_ascii=False, allow_nan=False) + "\n")
    with (output / "metrics.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=METRIC_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary = {"built_at": datetime.now(timezone.utc).isoformat(), "manifest": manifest,
               "question_count": len(questions), "top_k": top_k, "metrics": rows,
               "question_counts_by_split": {split: sum(q["split"] == split for q in questions)
                                             for split in ("dev", "test")},
               "metric_grouping": ["split", "mode"],
               "metric_unit": "chunk", "fake": fake,
               "label_completeness": "由标注提供者声明；不完备标注会影响召回率解释",
               "tuning_policy": "仅使用开发集调参；本入口不自动选择参数"}
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary
