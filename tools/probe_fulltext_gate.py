"""ING-001 live dev verification against frozen real PDFs; no automatic OCR.

Run on a NEW marked dev library, with real SiliconFlow services already configured. The
original 50-paper dev library and production are read-only protected controls.
Receipts contain metadata/counts/hashes, never PDF body text or credentials.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.catalog_batch import LocalAPI, code_identity, digest
from dlrag.ingestion.parser import parse_pdf
from dlrag.ingestion.fulltext import require_complete_text, FulltextReviewRequired


def write(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def compact(snapshot):
    return {"status": snapshot["status"], "documents": len(snapshot["documents"]),
            "manifest": snapshot["manifest"], "snapshot_sha256": digest(snapshot)}


def run(args):
    if args.output.exists():
        raise FileExistsError("Use a new output directory")
    identity = code_identity()
    if identity["dirty"]:
        raise ValueError("Commit the candidate and probe before formal execution")
    api = LocalAPI(args.api)
    marker = api.request("GET", "/validation/environment")
    expected_storage = hashlib.sha256(str(args.data_dir.resolve()).encode()).hexdigest()
    if (not marker.get("validation_only") or marker["code"] != identity
            or marker["storage_identity"] != expected_storage):
        raise ValueError("Expected this exact clean candidate and isolated dev storage")
    if api.snapshot()["documents"]:
        raise ValueError("Live probe requires an empty new dev corpus")
    protected = {p: LocalAPI("http://127.0.0.1:" + str(p)) for p in (18000, 19000)}
    if args.api.rstrip("/") in {client.base_url for client in protected.values()}:
        raise ValueError("Protected libraries may not be written")
    before = {p: client.snapshot() for p, client in protected.items()}
    catalog = {r["item_id"]: r for r in json.loads(args.catalog.read_text(encoding="utf-8"))["items"]}
    inputs = json.loads((args.source_dir / "input.json").read_text(encoding="utf-8"))["items"]
    imported_inputs = {r["item_id"]: r for r in inputs}
    args.output.mkdir(parents=True)
    report = {"work_item": "ING-001", "created_at": datetime.now(timezone.utc).isoformat(),
              "tested_code": identity, "backend_marker": marker,
              "runner_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "scope": "real frozen PDFs, actual document jobs, real cloud embeddings; one extra metadata preview",
              "protected_before": {str(p): compact(s) for p, s in before.items()},
              "metadata_reference": "external AI-assisted bibliography, not new user human review",
              "compatibility_scan": [], "cases": [], "passed": False}

    def checkpoint():
        write(args.output / "summary.json", report)

    def data(ident, derived=False):
        row = catalog[ident]
        path = ((args.source_dir / imported_inputs[ident]["pdf_path"]).resolve() if derived
                else args.source_dir / "pdfs" / (ident + ".pdf"))
        payload = path.read_bytes()
        expected = row["import_sha256" if derived else "source_sha256"]
        if hashlib.sha256(payload).hexdigest() != expected:
            raise ValueError("Frozen PDF hash differs")
        return payload, expected

    def submit(ident, *, derived=False, kind="import", label=None):
        payload, sha = data(ident, derived)
        row = catalog[ident]
        if kind == "metadata":
            route, form = "/documents/metadata/jobs", {"use_api": "true", "use_lookup": "false"}
        else:
            metadata = {"title": row["title"], "authors": row["authors"], "year": row["reference_year"],
                        "source_url": row["source_url"], "language": "en",
                        "topics": [row["category"], "ING-001-dev"] + (["正文待核对"] if ident == "HU08" else [])}
            route, form = "/documents/jobs", {"metadata_json": json.dumps(metadata)}
        job_id = api.request("POST", route, files={"file": (ident + ".pdf", payload, "application/pdf")}, data=form)["job_id"]
        deadline = time.monotonic() + 240
        while True:
            job = api.request("GET", "/document-jobs/" + job_id)
            if job["stage"] in {"done", "error"}:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("Inspect the in-flight dev job before any resubmission")
            time.sleep(.25)
        case = {"case": label or ident, "item_id": ident, "input_sha256": sha,
                "kind": kind, "job_id": job_id, "stage": job["stage"],
                "stages": job["stages"], "error": job["error"], "elapsed_seconds": job["elapsed_seconds"]}
        write(args.output / ((label or ident) + "-raw-job.json"), job)
        case["raw_job_sha256"] = hashlib.sha256((args.output / ((label or ident) + "-raw-job.json")).read_bytes()).hexdigest()
        if kind == "import":
            doc_id = "d_" + sha
            doc = api.request("GET", "/documents/" + doc_id)["document"]
            case["document"] = doc
            with sqlite3.connect(args.data_dir.joinpath("library.sqlite").resolve().as_uri() + "?mode=ro", uri=True) as db:
                case["stored_pages"] = db.execute("SELECT count(*) FROM pages WHERE doc_id=?", (doc_id,)).fetchone()[0]
                case["chunk_count"] = db.execute("SELECT count(*) FROM chunks WHERE doc_id=?", (doc_id,)).fetchone()[0]
                case["pages_with_chunks"] = [r[0] for r in db.execute("SELECT DISTINCT pdf_page FROM chunks WHERE doc_id=? ORDER BY pdf_page", (doc_id,))]
        else:
            preview = job.get("result") or {}
            case["api_assistance"] = preview.get("api_assistance")
            case["metadata"] = preview.get("metadata")
        report["cases"].append(case)
        checkpoint()
        print(case["case"], case["stage"], (case["error"] or {}).get("code", "ready/preview"), flush=True)
        return case

    try:
        for item in inputs:
            ident = item["item_id"]
            _, sha = data(ident, True)
            pages = parse_pdf((args.source_dir / item["pdf_path"]).resolve())
            row = {"item_id": ident, "import_sha256": sha, "page_count": len(pages)}
            try:
                require_complete_text(pages)
                row["gate_result"] = "accepted"
            except FulltextReviewRequired as exc:
                row.update(gate_result="requires_review", review=exc.review)
            report["compatibility_scan"].append(row)
        checkpoint()
        anchor = submit("SS01", label="normal-text")
        assert anchor["stage"] == "done" and anchor["document"]["status"] == "ready"
        frozen = api.snapshot()
        preview = submit("SS06", kind="metadata", label="enhanced-preview")
        report["metadata_preview_read_only"] = api.snapshot() == frozen
        assert report["metadata_preview_read_only"]
        assert preview["stage"] == "done" and preview["api_assistance"]["status"] == "completed"
        for ident, label, code, pages in [
            ("SS06", "original-mixed-scan", "FULLTEXT_REVIEW_REQUIRED", list(range(2, 22))),
            ("SS06", "repeated-blocked-original", "FULLTEXT_REVIEW_REQUIRED", None),
            ("SS14", "additional-mixed-scan", "FULLTEXT_REVIEW_REQUIRED", list(range(3, 26))),
            ("SS04", "pure-scan-boundary", "NO_EXTRACTABLE_TEXT", None)]:
            snapshot = api.snapshot()
            case = submit(ident, label=label)
            assert case["stage"] == "error" and case["error"]["code"] == code
            assert case["document"]["status"] == "failed" and case["stored_pages"] == case["chunk_count"] == 0
            if pages:
                assert case["error"]["fulltext_review"]["suspect_pages"] == pages
            after = api.snapshot()
            case["active_index_unchanged"] = after["manifest"] == snapshot["manifest"]
            case["ready_documents_unchanged"] = [d["doc_id"] for d in after["documents"] if d["status"] == "ready"] == [d["doc_id"] for d in snapshot["documents"] if d["status"] == "ready"]
            assert case["active_index_unchanged"] and case["ready_documents_unchanged"]
            assert "document_processing" not in case["stages"]
            checkpoint()
        repaired = submit("SS06", derived=True, label="external-ocr-copy")
        assert repaired["stage"] == "done" and repaired["document"]["status"] == "ready"
        assert repaired["pages_with_chunks"] == list(range(1, 22))
        # ING-002 remains explicitly observable, not silently repaired by this gate.
        garbled = submit("HU08", label="unfixed-garbled-control")
        garbled["known_open_issue"] = "ING-002; nonempty garbled text is outside this missing-layer gate"
        assert garbled["stage"] == "done"
        old = api.snapshot()
        duplicate = submit("SS06", derived=True, label="repeat-ocr-copy")
        duplicate["snapshot_unchanged"] = api.snapshot() == old
        assert duplicate["snapshot_unchanged"]
        searches = []
        for mode in ("keyword", "vector", "hybrid"):
            result = api.request("POST", "/search", json={"query": "Job Market Signaling", "mode": mode, "top_k": 5})
            searches.append({"mode": mode, "found_in_top_5": any(h["chunk"]["doc_id"] == repaired["document"]["doc_id"] for h in result["hits"])})
        report["corrected_copy_title_smoke"] = searches
        report["final_dev"] = compact(api.snapshot())
        report["gate_cases_passed"] = True
        report["passed"] = all(r["found_in_top_5"] for r in searches)
    finally:
        after = {p: client.snapshot() for p, client in protected.items()}
        report["protected_after"] = {str(p): compact(s) for p, s in after.items()}
        report["protected_libraries_unchanged"] = before == after
        report["worktree_dirty_after"] = code_identity()["dirty"]
        checkpoint()
    if not report["passed"] or not report["protected_libraries_unchanged"]:
        raise ValueError("Inspect all results; trial did not meet every stated condition")
    print("ING-001 live trial complete; old 50-paper dev and production unchanged", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("catalog", "source-dir", "data-dir", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--api", default="http://127.0.0.1:19010")
    run(parser.parse_args())
