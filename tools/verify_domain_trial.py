"""Read-only domain-trial integrity and all title-query outcomes, including misses."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.catalog_batch import LocalAPI, code_identity, digest


def write(path, value):
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def verify(args):
    identity = code_identity()
    if identity["dirty"]:
        raise ValueError("Formal verifier requires a clean checkout")
    changed = subprocess.check_output(["git", "diff", "--name-only", args.expected_backend_commit,
                                       "HEAD", "--", "app/src/dlrag"], cwd=ROOT, text=True)
    if changed.strip():
        raise ValueError("Business source differs from the frozen backend")
    api = LocalAPI(args.api)
    marker = api.request("GET", "/validation/environment")
    if not marker.get("validation_only") or marker["code"]["commit"] != args.expected_backend_commit:
        raise ValueError("Incorrect validation server")
    receipt = json.loads((args.run_dir / "receipt.json").read_text(encoding="utf-8"))
    plan = json.loads((args.run_dir / "plan.json").read_text(encoding="utf-8"))
    if receipt["outcome"] != "completed" or not receipt["collection_delta_verified"]:
        raise ValueError("Import was not completed")
    if digest({k: v for k, v in plan.items() if k != "plan_sha256"}) != plan["plan_sha256"]:
        raise ValueError("Plan hash differs")
    tail = "0" * 64
    for n, line in enumerate((args.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines(), 1):
        event = json.loads(line)
        value = event.pop("event_sha256")
        if event["sequence"] != n or event["previous_sha256"] != tail or digest(event) != value:
            raise ValueError("Event chain differs")
        tail = value
    if tail != receipt["last_event_sha256"]:
        raise ValueError("Receipt and journal differ")
    review = {r["item_id"]: r for r in json.loads(args.review.read_text(encoding="utf-8"))["items"]}
    catalog = {r["item_id"]: r for r in json.loads(args.catalog.read_text(encoding="utf-8"))["items"]}
    before = api.snapshot()
    manifest = before["manifest"]
    docs = {d["doc_id"]: d for d in before["documents"]}
    if len(docs) != 50 or before["status"] != "ready" or manifest["embedding_backend"]["provider"] != "local-bge-fp16":
        raise ValueError("The expected real dev corpus is not ready")
    report = {"work_item": "COL-002", "verifier_code": identity, "backend_marker": marker,
              "business_source_unchanged_from_backend": True, "created_at": datetime.now(timezone.utc).isoformat(),
              "before_manifest": manifest, "event_chain_verified": True, "items": [],
              "retrieval_failures": [], "human_review": "pending", "integrity_passed": False,
              "evaluation_type": "accession integrity plus title-query smoke checks, not general retrieval accuracy"}
    path = args.data_dir / "library.sqlite"
    if not path.is_file():
        raise ValueError("Existing dev database is required")
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity failed")
        for item in plan["items"]:
            ident, doc_id = item["item_id"], item["expected_doc_id"]
            doc = docs[doc_id]
            expected = review[ident]
            if doc["status"] != "ready" or any(doc[k] != v for k, v in item["metadata"].items()):
                raise ValueError("Stored metadata differs from reviewed plan")
            if hashlib.sha256((args.data_dir / "raw" / (doc_id + ".pdf")).read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Stored PDF differs")
            pages = {p["pdf_page"]: p["normalized_text"] for p in db.execute(
                "SELECT pdf_page,normalized_text FROM pages WHERE doc_id=?", (doc_id,))}
            chunks = db.execute("SELECT * FROM chunks WHERE doc_id=? ORDER BY pdf_page,page_char_start", (doc_id,)).fetchall()
            if len(pages) != expected["page_count"] or len(chunks) != expected["predicted_chunks"]:
                raise ValueError("Stored page/chunk counts differ")
            for c in chunks:
                if (c["text"] != pages[c["pdf_page"]][c["page_char_start"]:c["page_char_end"]]
                        or len(c["text"]) != c["char_count"] or len(c["text"]) > 1200 or c["token_count"] is not None):
                    raise ValueError("Chunk provenance/counting contract failed")
            row = {"item_id": ident, "category": catalog[ident]["category"], "doc_id": doc_id,
                   "sha256": item["sha256"], "pages": len(pages), "chunks": len(chunks),
                   "pages_with_text": sum(bool(t.strip()) for t in pages.values()),
                   "pages_with_chunks": len({c["pdf_page"] for c in chunks}),
                   "all_chunk_offsets_verified": True, "searches": []}
            for mode in ("keyword", "vector", "hybrid"):
                check = {"mode": mode, "found_in_top_5": False}
                try:
                    search = api.request("POST", "/search", json={"query": item["metadata"]["title"], "mode": mode, "top_k": 5})
                    if search["index_version"] != manifest["index_version"]:
                        raise ValueError("Index changed")
                    own = [h for h in search["hits"] if h["chunk"]["doc_id"] == doc_id]
                    check.update(found_in_top_5=bool(own), rank=own[0]["rank"] if own else None)
                    if own:
                        chunk = own[0]["chunk"]
                        if api.request("GET", "/chunks/" + chunk["chunk_id"])["chunk"] != chunk:
                            raise ValueError("Retrieved chunk differs")
                        check.update(chunk_id=chunk["chunk_id"], pdf_page=chunk["pdf_page"])
                except Exception as exc:
                    check["error_type"] = type(exc).__name__
                if not check["found_in_top_5"]:
                    report["retrieval_failures"].append({"item_id": ident, **check})
                row["searches"].append(check)
            chunk_id = chunks[0]["chunk_id"]
            response = api.session.get(api.base_url + "/sources/" + chunk_id,
                params={"index_version": manifest["index_version"]}, timeout=(5, 30), allow_redirects=False)
            if response.status_code != 200 or "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("Original source page unavailable")
            row["source_page_endpoint_verified"] = True
            report["items"].append(row)
            write(args.output, report)
            print(ident + ": integrity checked; searches=" + str([x["found_in_top_5"] for x in row["searches"]]), flush=True)
        if db.execute("SELECT count(*) FROM chunks").fetchone()[0] != manifest["chunk_count"]:
            raise ValueError("Database and index counts differ")
    after = api.snapshot()
    if after != before:
        raise ValueError("Dev corpus changed during read-only verification")
    report.update(integrity_passed=True, index_unchanged=True, after_manifest=manifest,
                  document_count=len(docs), chunk_count=sum(r["chunks"] for r in report["items"]),
                  category_counts={name: sum(r["category"] == name for r in report["items"]) for name in ("社会科学", "人文")},
                  title_query_checks=150, source_page_checks=50,
                  smoke_all_passed=not report["retrieval_failures"], passed=not report["retrieval_failures"])
    write(args.output, report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run-dir", "data-dir", "review", "catalog", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--expected-backend-commit", required=True)
    parser.add_argument("--api", default="http://127.0.0.1:19000")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = verify(args)
    print(json.dumps({k: report[k] for k in ("integrity_passed", "smoke_all_passed", "title_query_checks", "category_counts")}))
    raise SystemExit(0 if report["passed"] else 1)
