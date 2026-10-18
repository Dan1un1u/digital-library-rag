"""通过 D 服务调用 B/C 公共接口；模拟记录与真实实验完全分离。"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter

from dlrag.api.services import assemble
from dlrag.shared.config import Settings
from dlrag.shared.models import AskRequest, Filters, SearchRequest

CATEGORIES = {"exact", "vague", "clarify", "multi_document", "unanswerable"}


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def normalized(question):
    return "".join(c.lower() for c in question if c.isalnum())


def collect(root, output):
    """仅汇总候选模板。近似改写分组与人工复核不能由此步骤代替。"""
    rows, seen, missing = [], set(), []
    for role in "ABCD":
        path = Path(root) / "handoff" / role / "candidate_questions.jsonl"
        if not path.exists():
            missing.append(role)
            continue
        for row in read_rows(path):
            key = normalized(row["question"])
            if key in seen:
                continue
            seen.add(key)
            row.update(candidate_source=role, usable_for_evaluation=False, review_status="pending",
                       reviewer=None, dataset_stage="candidate_template")
            rows.append(row)
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return {"candidate_count": len(rows), "missing_roles": missing, "stage": "candidate_template"}


def validate_dataset(rows, services, mode):
    ids, groups, questions = set(), {}, set()
    for row in rows:
        qid = row["question_id"]
        if qid in ids:
            raise ValueError("题目 ID 重复：" + qid)
        ids.add(qid)
        if row["split"] not in ("dev", "test") or row["category"] not in CATEGORIES:
            raise ValueError("split/category 非法：" + qid)
        AskRequest(question=row["question"], filters=Filters.model_validate(row.get("filters", {})))
        if row["expected_status"] not in ("answered", "needs_clarification", "insufficient_evidence"):
            raise ValueError("expected_status 非法：" + qid)
        key = normalized(row["question"])
        if key in questions:
            raise ValueError("重复题目：" + qid)
        questions.add(key)
        group = row.get("paraphrase_group", key)
        if group in groups and groups[group] != row["split"]:
            raise ValueError("近似改写组跨越 dev/test：" + qid)
        groups[group] = row["split"]
        if mode == "real":
            if row.get("usable_for_evaluation") is not True or not row.get("reviewer") or row.get("review_status") != "approved":
                raise ValueError("真实评估拒绝未复核候选题：" + qid)
            refs = row.get("relevant_chunk_ids", [])
            if row["expected_status"] == "answered" and (not refs or not row.get("evidence_groups")):
                raise ValueError("缺少参考证据：" + qid)
            store = services.require("library")
            if any(store.get_document(d) is None for d in row.get("relevant_doc_ids", [])):
                raise ValueError("参考文献不在本馆藏：" + qid)
            if any(store.get_chunk(c) is None for c in refs):
                raise ValueError("参考片段不在本馆藏：" + qid)
            if not set(refs) <= services.require("retriever").get_chunk_ids():
                raise ValueError("参考片段不在当前索引快照：" + qid)
            if any(store.get_chunk(c)["doc_id"] not in row.get("relevant_doc_ids", []) for c in refs):
                raise ValueError("片段与参考文献不对应：" + qid)
            if row["category"] == "multi_document" and len({store.get_chunk(c)["doc_id"] for c in refs}) < 2:
                raise ValueError("多文献题必须有至少两篇支持来源：" + qid)
            if any(not group or not set(group) <= set(refs) for group in row.get("evidence_groups", [])):
                raise ValueError("证据组不在参考片段集合：" + qid)
            if row["category"] == "unanswerable" and (refs or row.get("relevant_doc_ids") or row.get("evidence_groups")):
                raise ValueError("无答案题的参考 ID 应为空：" + qid)


def percentiles(values):
    if not values:
        return {"sample_count": 0, "median_ms": None, "p95_ms": None}
    return {"sample_count": len(values), "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[max(0, math.ceil(len(values) * .95) - 1)]}


def provenance(settings, services, dataset):
    try:
        root = Path(__file__).resolve().parents[1]
        git_root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True,
                                  text=True, timeout=5).stdout.strip()
        sha = (subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True,
                              timeout=5).stdout.strip() or None) if git_root and Path(git_root).resolve() == root else None
    except (OSError, subprocess.TimeoutExpired):
        sha = None
    dependencies = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()}
    return {"created_at": datetime.now(timezone.utc).isoformat(), "git_version": sha,
            "source_snapshot": source_snapshot(),
            "python": sys.version, "dependencies": dependencies, "configuration": settings.public(),
            "dataset_sha256": hashlib.sha256(Path(dataset).read_bytes()).hexdigest(),
            "manifest": services.manifest(), "human_metrics": "未评估：需要独立人工语义标注"}


def source_snapshot():
    """Hash the source actually executed, including local changes without Git."""
    root = Path(__file__).resolve().parents[1]
    paths = sorted([*root.glob("src/**/*.py"), *root.glob("src/**/*.txt"),
                    *root.glob("src/**/*.sql"), *root.glob("scripts/*.py"), root / "pyproject.toml"])
    files = {str(path.relative_to(root)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in paths if path.is_file()}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {"sha256": digest, "files": files, "method": "sorted_relative_paths_and_file_sha256"}


def metric(values):
    return {"value": statistics.mean(values) if values else None, "denominator": len(values)}


def evaluate(rows, services, mode, retrieval_mode, output):
    results = []
    initial = services.manifest()
    for row in rows:
        start = perf_counter()
        item = {"question_id": row["question_id"], "split": row["split"], "category": row["category"],
                "question": row["question"], "filters": row.get("filters", {}), "mode": mode,
                "retrieval_mode": retrieval_mode, "index_version": initial["index_version"] if initial else None}
        try:
            if services.manifest() != initial:
                raise ValueError("实验期间索引变化，停止比较")
            search = services.search(SearchRequest(query=row["question"], filters=row.get("filters", {}), mode=retrieval_mode, top_k=20))
            answer = services.ask(AskRequest(question=row["question"], filters=row.get("filters", {})))
            item.update(search=search, answer=answer)
            item["outcome"] = "error" if answer["status"] == "error" else "ok"
            if answer["status"] == "error":
                item["failure_code"] = answer["error"]["code"]
            item["expected_status_match"] = answer["status"] == row["expected_status"]
            refs = set(row.get("relevant_chunk_ids", []))
            eligible = mode == "real" and row.get("usable_for_evaluation") is True
            ranked = [h["chunk"]["chunk_id"] for h in search["hits"]]
            item["reference_state"] = "available" if refs else "no_reference_evidence"
            item["retrieval_metrics"] = {"hit_at_5": int(bool(refs.intersection(ranked[:5]))) if eligible and refs else None,
                                          "recall_at_5": len(refs.intersection(ranked[:5])) / len(refs) if eligible and refs else None,
                                          "recall_at_10": len(refs.intersection(ranked[:10])) / len(refs) if eligible and refs else None,
                                          "evidence_group_coverage": None}
            evidence_groups = row.get("evidence_groups", [])
            if eligible and evidence_groups:
                item["retrieval_metrics"]["evidence_group_coverage"] = sum(bool(set(g).intersection(ranked)) for g in evidence_groups) / len(evidence_groups)
        except Exception as exc:
            item.update(outcome="error", failure_code=getattr(exc, "code", "EVALUATION_ERROR"))
        item["elapsed_ms"] = (perf_counter() - start) * 1000
        results.append(item)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in results), encoding="utf-8")
    summaries = {}
    for split in sorted({r["split"] for r in results}):
        group = [r for r in results if r["split"] == split]
        good = [r for r in group if r["outcome"] == "ok"]
        summaries[split] = {"total": len(group), "failures": len(group) - len(good),
                            "timings": percentiles([r["elapsed_ms"] for r in group]),
                            "missing_reference_evidence": sum(r.get("reference_state") == "no_reference_evidence" for r in group),
                            "metrics": {key: metric([r["retrieval_metrics"][key] for r in good if r["retrieval_metrics"][key] is not None])
                                        for key in ["hit_at_5", "recall_at_5", "recall_at_10", "evidence_group_coverage"]},
                            "expected_status_match": metric([int(r.get("expected_status_match", False)) for r in group]) if mode == "real" else {"value": None, "denominator": 0},
                            "human_semantic_metrics": None}
    summary = {"mode": mode, "real_experiment": mode == "real", "by_split": summaries,
               "empty_dataset": not rows, "human_metrics_status": "未评估", "mock_scores_excluded": mode == "mock"}
    write_json(output / "summary.json", summary)
    # 人工评审以结论与引用关系为单位；空白项绝不算支持。
    import csv
    with (output / "human_review.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["question_id", "claim_id", "evidence_id", "support_full_partial_none", "claim_sufficiently_supported", "reference_point_score", "reviewer", "comment"])
        for row in results:
            for claim in row.get("answer", {}).get("claims", []):
                for eid in claim["evidence_ids"]:
                    writer.writerow([row["question_id"], claim["claim_id"], eid, "", "", "", "", ""])
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("evaluation/dataset/questions.jsonl"))
    parser.add_argument("--mode", choices=["real", "mock"])
    parser.add_argument("--retrieval-mode", choices=["keyword", "vector", "hybrid"], default="hybrid")
    parser.add_argument("--planning-enabled", choices=["true", "false"], default="true")
    parser.add_argument("--output", type=Path, default=Path("evaluation/reports/runs"))
    parser.add_argument("--collect", action="store_true")
    parser.add_argument("--source-dir", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    if args.collect:
        print(json.dumps(collect(args.source_dir, args.dataset), ensure_ascii=False))
        return 0
    if not args.mode:
        parser.error("必须显式指定 --mode real 或 mock")
    options = {"app_mode": args.mode, "planning_enabled": args.planning_enabled == "true", "retrieval_mode": args.retrieval_mode}
    settings = Settings(**options)
    services = assemble(settings)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    output = args.output / args.mode / (stamp + "_" + args.retrieval_mode)
    output.mkdir(parents=True, exist_ok=False)
    try:
        rows = read_rows(args.dataset)
        if args.mode == "real" and not rows:
            raise ValueError("真实评估题集为空，未执行实验")
        meta = provenance(settings, services, args.dataset)
        write_json(output / "environment.json", meta)
        validate_dataset(rows, services, args.mode)
        if args.mode == "real":
            health = services.health()
            if health["status"] != "ready":
                raise ValueError("真实模式缺少模型、模块或索引，未执行真实实验")
            manifest = services.manifest()
            if any(row.get("frozen_index_version") != manifest["index_version"] for row in rows):
                raise ValueError("题集未冻结到当前索引版本")
            if any(row.get("frozen_corpus_hash") != manifest["corpus_hash"] for row in rows):
                raise ValueError("题集语料哈希与索引不同")
        with services.lock:
            summary = evaluate(rows, services, args.mode, args.retrieval_mode, output)
        print(json.dumps({"output": str(output), **summary}, ensure_ascii=False))
        return 1 if any(s["failures"] for s in summary["by_split"].values()) else 0
    except (ValueError, KeyError, OSError) as exc:
        write_json(output / "not_executed.json", {"status": "not_executed", "mode": args.mode, "reason": str(exc)})
        print("评估未执行：" + str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
