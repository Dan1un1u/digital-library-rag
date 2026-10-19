"""Run one work item's target checks or explicitly request inherited regression."""
import argparse
from datetime import datetime, timezone
from importlib.metadata import version
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NEW_TESTS = ["app/tests/integration/test_ingestion_recovery.py", "app/tests/integration/test_catalog_batch.py",
             "app/tests/ingestion/test_metadata_known_issues.py", "app/tests/ingestion/test_metadata_year.py",
             "app/tests/integration/test_metadata_year_api.py", "app/tests/ingestion/test_bibliography.py",
             "app/tests/integration/test_bibliography_api.py", "app/tests/integration/test_domain_trial_guards.py",
             "app/tests/integration/test_fulltext_gate.py"]
CASE_FILES = {"COL-001": NEW_TESTS[:-2], "COL-002": [NEW_TESTS[-2]], "ING-001": [NEW_TESTS[-1]]}
CASE_FILES["ING-002"] = ["app/tests/integration/test_text_quality_gate.py"]
NEW_TESTS += CASE_FILES["ING-002"]
CASE_FILES["MQ-005"] = ["app/tests/ingestion/test_issue_year.py", "app/tests/integration/test_issue_year_api.py"]
NEW_TESTS += CASE_FILES["MQ-005"]
CASE_FILES["RET-001"] = ["app/tests/retrieval/test_title_vectors.py"]
NEW_TESTS += CASE_FILES["RET-001"]
CASE_FILES["DEP-001"] = ["app/tests/integration/test_siliconflow_portability.py"]
NEW_TESTS += CASE_FILES["DEP-001"]
CASE_FILES["MQ-006"] = ["app/tests/integration/test_discipline_ingestion.py",
                         "app/tests/integration/test_discipline_assistance.py"]
NEW_TESTS += CASE_FILES["MQ-006"]
FOCUS = ["app/src/dlrag/api/services.py", "app/src/dlrag/ingestion/library.py",
         "app/src/dlrag/ingestion/parser.py", "app/src/dlrag/ingestion/chunker.py",
         "app/src/dlrag/retrieval/retriever.py", "tools/catalog_batch.py",
         "app/src/dlrag/ingestion/metadata_api.py", "app/src/dlrag/ingestion/metadata_year.py",
         "app/src/dlrag/ingestion/bibliography.py", "app/src/dlrag/ingestion/fulltext.py",
         "app/src/dlrag/ingestion/text_quality.py", "app/src/dlrag/shared/disciplines.py",
         "app/src/dlrag/api/routes.py", "app/src/dlrag/ingestion/discipline.py"]


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=["new", "all"], default="all")
    parser.add_argument("--work-item", choices=list(CASE_FILES), default="ING-001")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--tokenizer-cache", type=Path)
    args = parser.parse_args()
    output = (args.output or ROOT / "reports" / args.work_item /
              (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + args.scope)).resolve()
    output.mkdir(parents=True, exist_ok=False)
    import dlrag
    source_path = Path(next(iter(dlrag.__path__))).resolve()
    if source_path != ROOT / "app/src/dlrag":
        raise RuntimeError("Refusing to measure a different deployment's source")
    before = {"commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
              "dirty": bool(git("status", "--porcelain"))}
    if before["dirty"]:
        raise RuntimeError("Commit this task's source before formal checks")
    env = os.environ.copy()
    env.update(APP_MODE="mock", PYTHONUTF8="1", PYTHONIOENCODING="utf-8",
               SILICONFLOW_API_KEY="", LLM_API_KEY="", SD_EMBEDDING_KEY="",
               EMBEDDING_PROVIDER="siliconflow", LLM_PROVIDER="siliconflow",
               QA_RERANK_PROVIDER="siliconflow", METADATA_API_PROVIDER="siliconflow")
    env["TIKTOKEN_CACHE_DIR"] = str((args.tokenizer_cache or ROOT / "app/data/tokenizer-cache").resolve())
    command = [sys.executable, "-m", "coverage", "run", "--rcfile=" + str(ROOT / ".coveragerc"),
               "--data-file=" + str(output / ".coverage"), "-m", "pytest", "-q",
               "-c", "app/pyproject.toml", *(CASE_FILES[args.work_item] if args.scope == "new" else ["app/tests"]),
               "--junitxml=" + str(output / "junit.xml")]
    started = time.monotonic()
    result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    (output / "pytest.txt").write_text(result.stdout, encoding="utf-8")
    print(result.stdout)
    coverage_result = subprocess.run([sys.executable, "-m", "coverage", "json",
                                     "--rcfile=" + str(ROOT / ".coveragerc"),
                                     "--data-file=" + str(output / ".coverage"),
                                     "-o", str(output / "coverage.json")], cwd=ROOT, env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if coverage_result.returncode:
        print(coverage_result.stdout)
        return 1
    coverage = json.loads((output / "coverage.json").read_text(encoding="utf-8"))
    suites = ET.parse(output / "junit.xml").getroot().findall("testsuite")
    cases = [case for suite in suites for case in suite.findall("testcase")]
    new_names = {Path(path).stem for path in CASE_FILES[args.work_item]}
    new_count = sum(case.attrib.get("classname", "").split(".")[-1] in new_names for case in cases)
    counts = {group: sum(case.attrib.get("classname", "").split(".")[-1]
                        in {Path(path).stem for path in files} for case in cases)
              for group, files in CASE_FILES.items()}
    expected_failures = sum(case.find("skipped") is not None and
                            case.find("skipped").attrib.get("type") == "pytest.xfail" for case in cases)
    incremental_groups = {"COL-001": ["COL-001"], "COL-002": ["COL-002"],
                          "ING-001": ["COL-002", "ING-001"], "ING-002": ["ING-002"],
                          "MQ-005": ["MQ-005"], "RET-001": ["RET-001"],
                          "DEP-001": ["DEP-001"], "MQ-006": ["MQ-006"]}[args.work_item]
    incremental_count = sum(counts[g] for g in incremental_groups)
    summary = {"work_item": args.work_item, "scope": args.scope, "tested_code": before,
               "created_at": datetime.now(timezone.utc).isoformat(),
               "python": sys.version.split()[0], "platform": sys.platform,
               "packages": {name: version(name) for name in ["pytest", "coverage", "PyMuPDF", "numpy", "requests"]},
               "source_path_verified": True, "environment": "isolated temporary stores; mock embeddings; no live model calls",
               "exit_code": result.returncode, "duration_seconds": round(time.monotonic() - started, 2),
               "tests": {k: sum(int(s.attrib.get(k, 0)) for s in suites)
                         for k in ["tests", "failures", "errors", "skipped"]},
               "new_cases": new_count, "reused_cases": len(cases) - new_count,
               "case_count_policy": "new_cases selects one work item; stacked PR increments use incremental_groups; old reports retain original attribution",
               "pr_incremental_groups": incremental_groups,
               "pr_incremental_cases": incremental_count,
               "pr_inherited_cases": len(cases) - incremental_count,
               "case_groups": {**counts, "baseline_reused": len(cases) - sum(counts.values())},
               "expected_failures": expected_failures,
               "coverage": {}, "uncovered_focus": {}, "manual_review": "pending",
               "real_pdf_batch": "not exercised by this offline test run; see separate batch evidence"}
    for name, row in coverage["files"].items():
        name = name.replace("\\", "/")
        metrics = row["summary"]
        statements, branches = metrics["num_statements"], metrics["num_branches"]
        summary["coverage"][name] = {
            "statements": statements, "covered_statements": metrics["covered_lines"],
            "statement_percent": round(100 * metrics["covered_lines"] / statements, 2) if statements else None,
            "branches": branches, "covered_branches": metrics["covered_branches"],
            "branch_percent": round(100 * metrics["covered_branches"] / branches, 2) if branches else None}
        if name in FOCUS:
            summary["uncovered_focus"][name] = {"missing_lines": row["missing_lines"],
                                                 "missing_branches": row["missing_branches"]}
    summary["worktree_dirty_after"] = bool(git("status", "--porcelain"))
    summary["artifact_sha256"] = {}
    import hashlib
    for name in ["pytest.txt", "junit.xml", "coverage.json"]:
        summary["artifact_sha256"][name] = hashlib.sha256((output / name).read_bytes()).hexdigest()
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"tests": summary["tests"], "new": new_count,
                      "reused": summary["reused_cases"], "tested_code": before, "output": str(output)}, ensure_ascii=False))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
