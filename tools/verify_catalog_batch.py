"""Read-only accession checks: chain, SQLite provenance and live search smoke tests.

This checks stored identity/offsets and title-query retrieval, not metadata
recognition accuracy or a human-judged retrieval benchmark.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.catalog_batch import LocalAPI, canonical, code_identity, digest


def verify(run_dir, data_dir, review, api):
    receipt = json.loads((run_dir / "receipt.json").read_text(encoding="utf-8"))
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    if receipt["outcome"] != "completed" or not receipt["collection_delta_verified"]:
        raise ValueError("Import receipt is incomplete")
    expected_review = {i["item_id"]: i for i in review["items"]}
    tail = "0" * 64
    events = (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    for sequence, line in enumerate(events, 1):
        event = json.loads(line)
        recorded = event.pop("event_sha256")
        if event["previous_sha256"] != tail or event["sequence"] != sequence or digest(event) != recorded:
            raise ValueError("Invalid event chain")
        tail = recorded
    if tail != receipt["last_event_sha256"] or receipt["plan_sha256"] != plan["plan_sha256"]:
        raise ValueError("Receipt hash mismatch")
    before = json.loads((run_dir / "before.json").read_text(encoding="utf-8"))
    after = api.snapshot()
    manifest = after["manifest"]
    if after["status"] != "ready" or manifest["embedding_backend"]["provider"] != "siliconflow":
        raise ValueError("Real SiliconFlow index is not ready")
    docs = {d["doc_id"]: d for d in after["documents"]}
    expected_new = {i["expected_doc_id"] for i in plan["items"]} - {d["doc_id"] for d in before["documents"]}
    if set(docs) - {d["doc_id"] for d in before["documents"]} != expected_new:
        raise ValueError("Unexpected collection delta")
    db_path = data_dir / "library.sqlite"
    if not db_path.is_file():
        raise ValueError("Existing library.sqlite required")
    result = {"batch_id": plan["batch_id"], "created_at": datetime.now(timezone.utc).isoformat(),
              "verification_code": code_identity(), "import_code": receipt["code"],
              "evaluation_type": "accession integrity and title-query smoke test; not recognition accuracy or quality benchmark",
              "last_event_sha256": tail, "event_chain_verified": True,
              "before_manifest": before["manifest"], "after_manifest": manifest,
              "human_review": "pending", "items": []}
    with sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity failed")
        counts = {"documents": db.execute("SELECT count(*) FROM documents").fetchone()[0],
                  "chunks": db.execute("SELECT count(*) FROM chunks").fetchone()[0]}
        if counts != {"documents": manifest["document_count"], "chunks": manifest["chunk_count"]}:
            raise ValueError("Database/index count mismatch")
        for item in plan["items"]:
            identity = item["expected_doc_id"]
            doc = docs[identity]
            expected = expected_review[item["item_id"]]
            if doc["status"] != "ready" or doc["file_sha256"] != item["sha256"]:
                raise ValueError("Document state or hash mismatch")
            if any(doc[k] != value for k, value in item["metadata"].items()):
                raise ValueError("Stored metadata differs from externally reviewed plan")
            if hashlib.sha256((data_dir / "raw" / (identity + ".pdf")).read_bytes()).hexdigest() != item["sha256"]:
                raise ValueError("Stored PDF bytes differ from input hash")
            pages = {p["pdf_page"]: p["normalized_text"] for p in db.execute(
                "SELECT pdf_page,normalized_text FROM pages WHERE doc_id=?", (identity,))}
            chunks = db.execute("SELECT * FROM chunks WHERE doc_id=? ORDER BY pdf_page,page_char_start", (identity,)).fetchall()
            if len(pages) != expected["page_count"] or len(chunks) != expected["predicted_chunks"]:
                raise ValueError("Page/chunk count differs from preflight")
            for chunk in chunks:
                start, end, text = chunk["page_char_start"], chunk["page_char_end"], chunk["text"]
                if (text != pages[chunk["pdf_page"]][start:end] or end - start != len(text)
                        or chunk["token_count"] is not None or len(text) > 1200):
                    raise ValueError("Chunk page provenance/counting contract failed")
            row = {"item_id": item["item_id"], "doc_id": identity, "sha256": item["sha256"],
                   "pages": len(pages), "chunks": len(chunks), "status": "ready",
                   "stored_metadata_matches_reviewed_plan": True, "all_chunk_offsets_verified": True,
                   "searches": []}
            for mode in ("keyword", "vector", "hybrid"):
                search = api.request("POST", "/search", json={"query": item["metadata"]["title"], "mode": mode, "top_k": 5})
                hits = search["hits"]
                target_hits = [h for h in hits if h["chunk"]["doc_id"] == identity]
                if not target_hits or search["index_version"] != manifest["index_version"]:
                    raise ValueError("Title-query smoke test failed for " + item["item_id"] + "/" + mode)
                hit = target_hits[0]
                chunk = hit["chunk"]
                retrieved = api.request("GET", "/chunks/" + chunk["chunk_id"])["chunk"]
                if retrieved != chunk or chunk["text"] != pages[chunk["pdf_page"]][chunk["page_char_start"]:chunk["page_char_end"]]:
                    raise ValueError("Retrieved chunk/page mismatch")
                row["searches"].append({"mode": mode, "found_in_top_5": True, "rank": hit["rank"],
                                        "chunk_id": chunk["chunk_id"], "pdf_page": chunk["pdf_page"],
                                        "page_char_start": chunk["page_char_start"], "page_char_end": chunk["page_char_end"],
                                        "text_sha256": hashlib.sha256(chunk["text"].encode()).hexdigest()})
            source_hit = row["searches"][0]
            response = api.session.get(api.base_url + "/sources/" + source_hit["chunk_id"],
                                       params={"index_version": manifest["index_version"]},
                                       timeout=(5, 30), allow_redirects=False)
            if response.status_code != 200 or "text/html" not in response.headers.get("content-type", ""):
                raise ValueError("Source page cannot be opened")
            row["source_page_endpoint_verified"] = True
            result["items"].append(row)
            print(item["item_id"] + ": identity, offsets, keyword/vector/hybrid and source page checked", flush=True)
    if api.snapshot()["manifest"] != manifest:
        raise ValueError("Index changed during verification")
    result.update(passed=True, sqlite_integrity="ok", added_documents=len(expected_new),
                  added_chunks=sum(r["chunks"] for r in result["items"]),
                  title_query_checks=sum(len(r["searches"]) for r in result["items"]))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--api", default="http://127.0.0.1:18000")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new output path")
    result = verify(args.run_dir, args.data_dir,
                    json.loads(args.review.read_text(encoding="utf-8")), LocalAPI(args.api))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print(canonical({k: result[k] for k in ("passed", "added_documents", "added_chunks", "title_query_checks")}))


if __name__ == "__main__":
    main()
