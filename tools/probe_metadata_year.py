"""Read-only shadow preview of the MQ-003 candidate using the configured real LLM.

The existing backend is only read for a before/after index snapshot. PDFs are
previewed by this checkout's code; no document import or index build is called.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.catalog_batch import LocalAPI, code_identity
from dlrag.ingestion import metadata_api
from dlrag.ingestion.metadata import extract_metadata
from dlrag.shared.config import Settings


def write(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True, help="Local JSON list with pdf_path/SHA256/expected_year")
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api", default="http://127.0.0.1:18000")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text(encoding="utf-8-sig"))
    payloads = []
    for case in cases:
        path = (args.cases.resolve().parent / case["pdf_path"]).resolve()
        if hashlib.sha256(path.read_bytes()).hexdigest() != case["sha256"]:
            parser.error("Case input SHA256 changed")
        payloads.append(path)
    settings = Settings(_env_file=args.env_file)
    if settings.app_mode != "real" or not settings.metadata_api_enabled:
        parser.error("Real mode and enabled metadata assistance required")
    import dlrag
    if Path(next(iter(dlrag.__path__))).resolve() != ROOT / "app/src/dlrag":
        parser.error("Different deployment source imported")
    args.output.mkdir(parents=True, exist_ok=False)
    api = LocalAPI(args.api)
    before = api.snapshot()["manifest"]
    result = {"code": code_identity(), "provider": settings.metadata_api_provider,
              "model": settings.metadata_api_model, "mode": "read-only shadow preview from this checkout",
              "production_code_deployed": False, "before_manifest": before,
              "cases": [], "passed": False, "human_review": "pending"}
    original = metadata_api.request_candidates
    captured = []

    def traced(settings, pages, local):
        reply = original(settings, pages, local)
        captured.append(copy.deepcopy(reply))
        return reply

    metadata_api.request_candidates = traced
    failure = None
    try:
        for case, path in zip(cases, payloads):
            row = {"case_id": case["case_id"], "sha256": case["sha256"], "expected_year": case["expected_year"]}
            result["cases"].append(row)
            print(case["case_id"] + ": starting real LLM metadata preview", flush=True)
            if case.get("replay_year_candidate"):
                replay = extract_metadata(path)
                with fitz.open(path) as pdf:
                    pages = [{"text": pdf[i].get_text(sort=True)} for i in range(min(2, len(pdf)))]
                metadata_api.merge_candidates(replay, {"year": case["replay_year_candidate"]}, pages)
                row["frozen_candidate_replay"] = {"before_year": case["replay_year_candidate"]["value"],
                                                   "after_year": replay["metadata"]["year"],
                                                   "year_review": replay["year_review"]}
                assert replay["metadata"]["year"] == case["expected_year"]
            captured.clear()
            preview = metadata_api.recognize_metadata(path, settings, filename=path.name, assist=True)
            row.update(api_assistance=preview["api_assistance"], metadata=preview["metadata"],
                       year_review=preview.get("year_review"), year_source=preview["field_sources"].get("year"),
                       warnings=preview["warnings"], raw_model_year=captured[0].get("year") if captured else None)
            row["passed"] = (preview["api_assistance"]["status"] == "completed"
                             and preview["metadata"]["year"] == case["expected_year"])
            write(args.output / "result.json", result)
            if not row["passed"]:
                raise ValueError("Unexpected preview result")
            print(case["case_id"] + ": passed, year=" + str(preview["metadata"]["year"]), flush=True)
        result["passed"] = True
    except Exception as exc:
        failure = type(exc).__name__  # Do not serialize provider errors/credentials.
        result["failure_type"] = failure
    finally:
        metadata_api.request_candidates = original
        after = api.snapshot()["manifest"]
        result["after_manifest"] = after
        result["production_index_unchanged"] = before == after
        result["passed"] = result["passed"] and before == after
        write(args.output / "result.json", result)
    print(json.dumps({"passed": result["passed"], "cases": len(result["cases"]),
                      "production_index_unchanged": result["production_index_unchanged"]}))
    return 0 if result["passed"] and failure is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
