"""Store reproducible runs and blank claim/evidence reviews; never invent semantic grades."""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from .errors import ProjectError

REVIEW_FIELDS = ["question_id", "split", "variant", "request_id", "claim_id", "evidence_id",
                 "claim_text", "quote", "support", "point_score", "point_max", "coverage",
                 "factual_issue", "reviewer", "notes"]


def write_csv(path, fields, rows):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def evaluate(engine, questions, output_dir, variant="full"):
    """One immutable output directory per run. Split labels remain separate."""
    if not isinstance(questions, list):
        raise ProjectError("INVALID_REQUEST", "评估题集必须为列表")
    ids = set()
    for q in questions:
        if (not isinstance(q, dict) or not isinstance(q.get("question_id"), str)
                or not q["question_id"] or q["question_id"] in ids
                or q.get("split") not in {"dev", "test"}
                or q.get("expected_status") not in {"answered", "needs_clarification", "insufficient_evidence", "error"}):
            raise ProjectError("INVALID_REQUEST", "题号、集合或预期状态非法")
        ids.add(q["question_id"])
    out = Path(output_dir)
    if out.exists() and any(out.iterdir()):
        raise ProjectError("INVALID_REQUEST", "评估输出目录必须为空，避免覆盖既有实验")
    out.mkdir(parents=True, exist_ok=True)
    config = engine.llm.get_config() if hasattr(engine.llm, "get_config") else {"mode": "injected", "model": "unknown"}
    runs, reviews = [], []
    for q in questions:
        r = engine.ask({"question": q.get("question"), "filters": q.get("filters", {}), "history": []})
        runs.append(dict(question=q, response=r, variant=variant, model_config=config,
                         settings=engine.settings, annotation_status=q.get("annotation_status", "unspecified")))
        evidence = {e["evidence_id"]: e for e in r["evidence"]}
        base = dict(question_id=q["question_id"], split=q["split"], variant=variant, request_id=r["request_id"])
        for claim in r["claims"]:
            for eid in claim["evidence_ids"]:
                reviews.append({**base, "claim_id": claim["claim_id"], "evidence_id": eid,
                                "claim_text": claim["text"], "quote": evidence[eid]["quote"]})
        if not r["claims"]:
            reviews.append(base)
    with (out / "runs.jsonl").open("w", encoding="utf-8") as f:
        for run in runs:
            f.write(json.dumps(run, ensure_ascii=False, allow_nan=False) + "\n")
    write_csv(out / "review_template.csv", REVIEW_FIELDS, reviews)
    rows = []
    for split in ("dev", "test"):
        subset = [x for x in runs if x["question"]["split"] == split]
        if not subset:
            continue
        eligible = [x for x in subset if x["question"].get("usable_for_evaluation") is True
                    and config.get("mode") == "real"]
        row = dict(split=split, variant=variant, count=len(subset), reviewed_eligible_count=len(eligible),
                   answered=sum(x["response"]["status"] == "answered" for x in subset),
                   errors=sum(x["response"]["status"] == "error" for x in subset),
                   answer_point_score="", citation_support_accuracy="", citation_coverage="",
                   clarification_hit_rate="", unanswerable_handling_rate="",
                   semantic_metrics_status="pending_human_review",
                   mean_total_ms=round(sum(x["response"]["timings_ms"]["total"] for x in subset) / len(subset), 3))
        for expected, field in [("needs_clarification", "clarification_hit_rate"), ("insufficient_evidence", "unanswerable_handling_rate")]:
            category = [x for x in eligible if x["question"]["expected_status"] == expected]
            if category:
                row[field] = sum(x["response"]["status"] == expected for x in category) / len(category)
        rows.append(row)
    fields = ["split", "variant", "count", "reviewed_eligible_count", "answered", "errors", "mean_total_ms",
              "answer_point_score", "citation_support_accuracy", "citation_coverage", "clarification_hit_rate",
              "unanswerable_handling_rate", "semantic_metrics_status"]
    write_csv(out / "metrics.csv", fields, rows)
    manifest = dict(created_at=datetime.now(timezone.utc).isoformat(), count=len(runs), variant=variant,
                    model_config=config, settings=engine.settings,
                    dataset_sha256=hashlib.sha256(json.dumps(questions, sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                    semantic_metrics_status="pending_human_review")
    prompt_owner = getattr(engine, "engine", engine)
    prompt_texts = {name: getattr(prompt_owner, name) for name in
                    ("planning_prompt", "answer_prompt", "repair_prompt") if hasattr(prompt_owner, name)}
    (out / "prompts.json").write_text(json.dumps(prompt_texts, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest["prompt_sha256"] = {name: hashlib.sha256(value.encode("utf-8")).hexdigest()
                                  for name, value in prompt_texts.items()}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def summarize_review(run_dir, review_path, output_path):
    """Aggregate completed human grades, enforcing complete claim-link coverage.

    point_score/point_max and coverage are question-level fields: fill once in
    the first row of each question, including questions with no claims.
    """
    runs = [json.loads(line) for line in (Path(run_dir) / "runs.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    with Path(review_path).open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    expected = {}
    for run in runs:
        q, r = run["question"], run["response"]
        if run["model_config"].get("mode") != "real" or q.get("usable_for_evaluation") is not True:
            continue
        links = {(c["claim_id"], eid) for c in r["claims"] for eid in c["evidence_ids"]}
        expected[(q["question_id"], r["request_id"], run["variant"])] = (q["split"], links or {("", "")})
    grades = []
    try:
        for key, (split, links) in expected.items():
            group = [row for row in rows if (row["question_id"], row["request_id"], row["variant"]) == key]
            if len(group) != len(links) or {(x["claim_id"], x["evidence_id"]) for x in group} != links:
                raise ValueError()
            if any(not row["reviewer"].strip() or row["split"] != split for row in group):
                raise ValueError()
            graded = [row for row in group if row["point_max"].strip()]
            if len(graded) != 1:
                raise ValueError()
            g = graded[0]
            score, maximum, coverage = float(g["point_score"]), float(g["point_max"]), float(g["coverage"])
            if not (0 <= score <= maximum and maximum > 0 and 0 <= coverage <= 1):
                raise ValueError()
            supports = [row["support"] for row in group if row["claim_id"]]
            if any(x not in {"supported", "partial", "unsupported"} for x in supports):
                raise ValueError()
            grades.append((split, key[2], score, maximum, coverage, supports))
    except (ValueError, KeyError):
        raise ProjectError("INVALID_REQUEST", "人工评审未完整填写、存在重复项或分值非法") from None
    result = []
    for split, variant in sorted({(g[0], g[1]) for g in grades}):
        group = [g for g in grades if g[:2] == (split, variant)]
        supports = [s for g in group for s in g[5]]
        result.append(dict(split=split, variant=variant, reviewed_questions=len(group),
                           answer_point_score=sum(g[2] for g in group) / sum(g[3] for g in group),
                           citation_support_accuracy=supports.count("supported") / len(supports) if supports else "",
                           citation_coverage=sum(g[4] for g in group) / len(group)))
    write_csv(output_path, ["split", "variant", "reviewed_questions", "answer_point_score",
                            "citation_support_accuracy", "citation_coverage"], result)
    return result
