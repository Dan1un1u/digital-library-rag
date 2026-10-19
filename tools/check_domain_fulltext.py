"""Reproduce three domain-trial full-text controls in new isolated mock stores.

These are real PDFs and actual import jobs. Mock vectors isolate the parsing and
ready-status decisions; this is not a real-model retrieval quality measurement.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.testclient import TestClient
from dlrag.shared.config import Settings
from dlrag.api.main import create_app
from tools.catalog_batch import LocalAPI, code_identity


def run(args):
    if args.data_dir.exists() or args.output.exists():
        raise FileExistsError("Use a new empty negative-control directory and output")
    identity = code_identity()
    if identity["dirty"]:
        raise ValueError("Commit the reproduction tool before execution")
    changes = subprocess.check_output(["git", "diff", "--name-only", args.expected_app_commit,
                                       "HEAD", "--", "app/src/dlrag"], cwd=ROOT, text=True)
    if changes.strip():
        raise ValueError("Business source differs from the frozen trial")
    catalog = {i["item_id"]: i for i in json.loads(args.catalog.read_text(encoding="utf-8"))["items"]}
    production = LocalAPI(args.production_api)
    before = production.snapshot()
    settings = Settings(app_mode="mock", data_dir=args.data_dir, _env_file=None)
    report = {"reproduction_code": identity, "original_app_commit": args.expected_app_commit,
              "business_source_unchanged": True,
              "scope": "real PDFs, actual import jobs, isolated mock vectors, curated reference metadata",
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "cases": []}
    with TestClient(create_app(settings=settings)) as client:
        for ident, kind in (("SS04", "pure_scan_known_boundary"), ("SS06", "mixed_cover_and_scanned_body"),
                            ("HU08", "garbled_text_layer")):
            item = catalog[ident]
            payload = (args.pdf_dir / (ident + ".pdf")).read_bytes()
            if hashlib.sha256(payload).hexdigest() != item["source_sha256"]:
                raise ValueError("Original PDF identity differs")
            metadata = {"title": item["title"], "authors": item["authors"], "year": item["reference_year"],
                        "topics": [item["category"], item["subfield"]], "language": "en", "source_url": item["source_url"]}
            response = client.post("/documents/jobs", files={"file": (ident + ".pdf", payload, "application/pdf")},
                                   data={"metadata_json": json.dumps(metadata)})
            response.raise_for_status()
            job_id = response.json()["job_id"]
            deadline = time.monotonic() + 30
            while True:
                job = client.get("/document-jobs/" + job_id).json()
                if job["stage"] in {"done", "error"}:
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError("Negative-control import did not finish")
                time.sleep(.05)
            row = {"item_id": ident, "case": kind, "source_sha256": item["source_sha256"],
                   "job_id": job_id, "stage": job["stage"], "error": job.get("error")}
            if job["stage"] == "done":
                doc = job["result"]["document"]
                row.update(document_status=doc["status"], document_error_code=doc.get("error_code"), page_count=doc["page_count"])
                with sqlite3.connect(settings.db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
                    pages = db.execute("SELECT pdf_page,normalized_text,diagnostics_json FROM pages WHERE doc_id=? ORDER BY pdf_page", (doc["doc_id"],)).fetchall()
                    chunks = db.execute("SELECT pdf_page,text FROM chunks WHERE doc_id=?", (doc["doc_id"],)).fetchall()
                row.update(stored_pages=len(pages), pages_with_text=sum(bool(p[1].strip()) for p in pages),
                           pages_with_chunks=len({c[0] for c in chunks}), chunk_count=len(chunks),
                           scanned_no_ocr_pages=[p[0] for p in pages if "SCANNED_PAGE_NO_OCR" in json.loads(p[2])])
                if ident == "HU08":
                    row["text_sample"] = pages[0][1][:65]
                    row["expected_visual_title_present_in_page_text"] = "modern moral philosophy" in pages[0][1].lower()
                    row["visual_reference"] = "Original p1 renders Modern Moral Philosophy, G. E. M. Anscombe, January 1958; coding-assistant visual check, not user human review"
            report["cases"].append(row)
            print(ident, row["stage"], row.get("pages_with_chunks"), flush=True)
    after = production.snapshot()
    report["production_unchanged"] = before == after
    report["production_manifest"] = after["manifest"]
    report["reproduced"] = (report["cases"][0]["stage"] == "error"
        and report["cases"][0]["error"]["code"] == "NO_EXTRACTABLE_TEXT"
        and report["cases"][1].get("document_status") == "ready" and report["cases"][1].get("pages_with_chunks") == 1
        and report["cases"][2].get("document_status") == "ready"
        and report["cases"][2].get("expected_visual_title_present_in_page_text") is False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    if not report["reproduced"] or not report["production_unchanged"]:
        raise ValueError("Controls did not reproduce or production changed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("catalog", "pdf-dir", "data-dir", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-app-commit", required=True)
    parser.add_argument("--production-api", default="http://127.0.0.1:18000")
    run(parser.parse_args())
