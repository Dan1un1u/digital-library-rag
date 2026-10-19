"""Read-only MQ-004 experiment using frozen enhanced candidates or real LLMs.

Crossref is queried live. The production backend is only read for snapshots;
this tool never imports documents or deploys code. PDFs/config stay local.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.catalog_batch import LocalAPI, code_identity
from dlrag.ingestion import bibliography, metadata_api
from dlrag.shared.config import Settings


def write(path, record):
    path.write_bytes((json.dumps(record, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--batch", type=Path, required=True, help="Archived metadata-review.json")
    parser.add_argument("--mode", choices=["replay", "live"], required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api", default="http://127.0.0.1:18000")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8-sig"))
    archived = {r["item_id"]: r for r in json.loads(args.batch.read_text(encoding="utf-8"))["items"]}
    paths = []
    for case in cases:
        path = (args.cases.resolve().parent / case["pdf_path"]).resolve()
        if hashlib.sha256(path.read_bytes()).hexdigest() != archived[case["case_id"]]["sha256"]:
            parser.error("PDF fingerprint differs from archived input")
        paths.append(path)
    import dlrag
    if Path(next(iter(dlrag.__path__))).resolve() != ROOT / "app/src/dlrag":
        parser.error("Different source imported")
    settings = Settings(_env_file=args.env_file)
    if settings.app_mode != "real" or not settings.metadata_lookup_enabled:
        parser.error("Real mode and enabled bibliographic lookup required")
    args.output.mkdir(parents=True, exist_ok=False)
    api = LocalAPI(args.api)
    before = api.snapshot()["manifest"]
    report = {"code": code_identity(), "mode": args.mode, "network": "live Crossref",
              "model": settings.metadata_api_model if args.mode == "live" else None,
              "production_code_deployed": False, "before_manifest": before, "cases": [],
              "passed": False, "human_review": "pending"}
    query, enrich = bibliography.query_crossref, bibliography.enrich_metadata
    captured, initial = [], []

    def traced_query(*a):
        records = query(*a)
        captured.extend(copy.deepcopy(records))
        return records

    def traced_enrich(result, settings):
        initial.append(copy.deepcopy(result["metadata"]))
        return enrich(result, settings)

    bibliography.query_crossref = traced_query
    bibliography.enrich_metadata = traced_enrich
    try:
        for case, path in zip(cases, paths):
            case_id = case["case_id"]
            captured.clear()
            initial.clear()
            print(case_id + ": " + args.mode + " preview and Crossref lookup", flush=True)
            if args.mode == "replay":
                preview = {"metadata": copy.deepcopy(archived[case_id]["api_candidates"]), "field_sources": {},
                           "warnings": [], "requires_confirmation": True,
                           "api_assistance": {"status": "historical_completed_candidates_replayed"}}
                traced_enrich(preview, settings)
            else:
                preview = metadata_api.recognize_metadata(path, settings, filename=path.name, assist=True, lookup=True)
            audit = preview["bibliographic_enrichment"]
            row = {"case_id": case_id, "sha256": archived[case_id]["sha256"],
                   "before_enrichment": initial[0] if initial else None,
                   "metadata": preview["metadata"], "api_assistance": preview["api_assistance"],
                   "bibliographic_enrichment": audit, "field_sources": preview["field_sources"],
                   "year_review": preview.get("year_review"), "warnings": preview["warnings"],
                   "crossref_records": captured.copy()}
            # The frozen reference is explicit experiment data, never a resolver mapping.
            row["expected"] = {k: case[k] for k in ("expected_year", "expected_source_url", "expected_doi")}
            row["passed"] = (audit["status"] == "completed"
                             and preview["metadata"]["year"] == case["expected_year"]
                             and preview["metadata"]["source_url"] == case["expected_source_url"]
                             and audit["candidates"][0]["doi"] == case["expected_doi"]
                             and (args.mode == "replay" or preview["api_assistance"]["status"] == "completed"))
            report["cases"].append(row)
            write(args.output / "result.json", report)
            if not row["passed"]:
                raise ValueError("Unexpected enrichment result")
            print(case_id + ": passed", flush=True)
        report["passed"] = True
    except Exception as exc:
        report["failure_type"] = type(exc).__name__
    finally:
        bibliography.query_crossref, bibliography.enrich_metadata = query, enrich
        after = api.snapshot()["manifest"]
        report["after_manifest"] = after
        report["production_index_unchanged"] = before == after
        report["passed"] = report["passed"] and before == after
        write(args.output / "result.json", report)
    print(json.dumps({"passed": report["passed"], "cases": len(report["cases"]),
                      "production_index_unchanged": report["production_index_unchanged"]}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
