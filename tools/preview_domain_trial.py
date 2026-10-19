"""Freeze independent domain-trial metadata results through an isolated API.

The 50 original PDFs are previewed without importing or editing metadata. This
does not deploy the candidate to production, and never writes production data.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.catalog_batch import LocalAPI, code_identity


def write(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def require_dev(api, identity):
    marker = api.request("GET", "/validation/environment")
    if marker.get("validation_only") is not True or marker.get("code") != identity:
        raise ValueError("Validation server identity differs from this checkout")
    return marker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--pdf-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api", default="http://127.0.0.1:19000")
    parser.add_argument("--production-api", default="http://127.0.0.1:18000")
    args = parser.parse_args()
    identity = code_identity()
    if identity["dirty"]:
        parser.error("Commit trial tools and catalog before formal execution")
    if args.api.rstrip("/") == args.production_api.rstrip("/"):
        parser.error("Production cannot be the preview/import target")
    api, production = LocalAPI(args.api), LocalAPI(args.production_api)
    marker = require_dev(api, identity)
    catalog_bytes = args.catalog.read_bytes()
    catalog = json.loads(catalog_bytes)
    entries = catalog["items"]
    payloads = []
    for item in entries:
        payload = (args.pdf_dir / (item["item_id"] + ".pdf")).read_bytes()
        if hashlib.sha256(payload).hexdigest() != item["source_sha256"]:
            parser.error("Original input identity changed")
        payloads.append(payload)
    args.output.mkdir(parents=True, exist_ok=False)
    before = api.snapshot()
    production_before = production.snapshot()
    report = {"work_item": "COL-002", "code": identity, "validation_environment": marker,
              "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
              "created_at": datetime.now(timezone.utc).isoformat(), "items": [],
              "before": before, "production_before": production_before,
              "human_review": "pending", "production_deployed": False}
    write(args.output / "summary.json", report)
    try:
        for item, payload in zip(entries, payloads):
            ident = item["item_id"]
            print(ident + ": starting enhanced preview + lookup", flush=True)
            row = {"item_id": ident, "source_sha256": item["source_sha256"]}
            report["items"].append(row)
            try:
                row["job_id"] = api.request("POST", "/documents/metadata/jobs",
                    files={"file": (ident + ".pdf", payload, "application/pdf")},
                    data={"use_api": "true", "use_lookup": "true"})["job_id"]
                deadline = time.monotonic() + 240
                while True:
                    job = api.poll(row["job_id"])
                    if job["stage"] in {"done", "error"}:
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError("Poll job manually before any new submission")
                    time.sleep(1)
                row["stage"] = job["stage"]
                if job["stage"] == "done":
                    row["preview"] = job["result"]
                else:
                    row["error_code"] = job["error"]["code"]
                write(args.output / (ident + ".json"), row)
                print(ident + ": " + row["stage"] + ", model=" + str(row.get("preview", {}).get("api_assistance"))
                      + ", year=" + str(row.get("preview", {}).get("metadata", {}).get("year")), flush=True)
            except Exception as exc:
                row["stage"] = "unknown"
                row["error_type"] = type(exc).__name__
                write(args.output / (ident + ".json"), row)
                # An unknown in-flight job must be resolved before proceeding.
                raise
            write(args.output / "summary.json", report)
    finally:
        report["after"] = api.snapshot()
        report["production_after"] = production.snapshot()
        report["preview_did_not_import"] = report["before"] == report["after"]
        report["production_unchanged"] = report["production_before"] == report["production_after"]
        report["all_jobs_completed"] = len(report["items"]) == len(entries) and all(r["stage"] == "done" for r in report["items"])
        write(args.output / "summary.json", report)
    return 0 if report["all_jobs_completed"] and report["preview_did_not_import"] and report["production_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
