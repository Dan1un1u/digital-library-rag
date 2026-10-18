"""Plan a local PDF batch, then explicitly apply it through existing document jobs.

Receipts omit pdf_path and never store HTTP bodies, credentials or PDF contents.
The hash chain detects edits when checked against a separately retained final hash;
it is not a signature or proof of human review. Run against a trusted local server.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import urlsplit

import requests
from dlrag.shared.models import Metadata

ROOT = Path(__file__).resolve().parents[1]
MAX_PDF_BYTES = 25 * 1024 * 1024


class BatchError(Exception):
    pass


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prepare(path):
    """Read/validate every file before any server writes; upload these same bytes."""
    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if raw.get("schema_version") != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", raw.get("batch_id", "")):
        raise BatchError("Invalid schema_version or batch_id")
    if not isinstance(raw.get("items"), list) or not raw["items"]:
        raise BatchError("Batch needs at least one item")
    items, payloads, ids, hashes = [], [], set(), set()
    for row in raw["items"]:
        item_id = row.get("item_id", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item_id) or item_id in ids:
            raise BatchError("Invalid or duplicate item_id")
        ids.add(item_id)
        source = (path.parent / row["pdf_path"]).resolve()
        if source.suffix.lower() != ".pdf" or not source.is_file():
            raise BatchError(f"{item_id}: PDF file missing or wrong extension")
        if not 0 < source.stat().st_size <= MAX_PDF_BYTES:
            raise BatchError(f"{item_id}: PDF must be 1 byte to 25 MiB")
        data = source.read_bytes()
        if not 0 < len(data) <= MAX_PDF_BYTES or b"%PDF-" not in data[:1024]:
            raise BatchError(f"{item_id}: invalid PDF header or size")
        sha = hashlib.sha256(data).hexdigest()
        if sha != row.get("sha256"):
            raise BatchError(f"{item_id}: SHA256 mismatch; do not silently accept changed input")
        if sha in hashes:
            raise BatchError(f"{item_id}: duplicate content inside batch; use a separate repeat-import batch")
        hashes.add(sha)
        metadata = Metadata.model_validate(row["metadata"]).model_dump()
        if not metadata["title"]:
            raise BatchError(f"{item_id}: explicit title required")
        review = row.get("review", {})
        if review.get("status") not in {"pending", "ready"}:
            raise BatchError(f"{item_id}: review.status must be pending or ready")
        if review["status"] == "ready" and (review.get("method") not in {
                "human_pdf_check", "automated_pdf_check"} or not str(review.get("evidence", "")).strip()):
            raise BatchError(f"{item_id}: ready requires a review method and evidence reference")
        previous = row.get("metadata_before")
        changes = None
        if previous is not None:
            previous = Metadata.model_validate(previous).model_dump()
            changes = {k: {"before": previous[k], "after": v}
                       for k, v in metadata.items() if previous[k] != v}
        items.append({"item_id": item_id, "sha256": sha, "bytes": len(data),
                      "expected_doc_id": "d_" + sha, "metadata": metadata,
                      "review": {k: review.get(k) for k in ("status", "method", "evidence")},
                      "metadata_changes": changes})
        payloads.append(data)
    plan = {"schema_version": 1, "batch_id": raw["batch_id"], "items": items}
    plan["plan_sha256"] = digest(plan)
    return plan, payloads


class Journal:
    def __init__(self, path):
        self.path, self.tail, self.sequence = path, "0" * 64, 0

    def add(self, event, **fields):
        self.sequence += 1
        row = {"sequence": self.sequence, "at": datetime.now(timezone.utc).isoformat(),
               "event": event, "previous_sha256": self.tail, **fields}
        self.tail = digest(row)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(canonical({**row, "event_sha256": self.tail}) + "\n")
            stream.flush()


class LocalAPI:
    def __init__(self, base_url):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment):
            raise BatchError("Use the trusted local library HTTP origin")
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.trust_env = False

    def request(self, method, route, **kwargs):
        try:
            response = self.session.request(method, self.base_url + route, timeout=(5, 30),
                                            allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise BatchError("HTTP transport failed; any submitted job may still be running") from None
        if not 200 <= response.status_code < 300:
            raise BatchError(f"HTTP_{response.status_code}: inspect the local service separately")
        return response.json()

    def snapshot(self):
        health = self.request("GET", "/health")
        documents = self.request("GET", "/documents?include_nonready=true")["documents"]
        keys = ("doc_id", "file_sha256", "status", "page_count", *Metadata.model_fields)
        return {"status": health["status"], "mode": health["mode"],
                "manifest": health.get("manifest"), "active_models": health.get("active_models"),
                "documents": sorted(({k: d.get(k) for k in keys} for d in documents),
                                    key=lambda d: d["doc_id"])}

    def submit(self, item, data):
        return self.request("POST", "/documents/jobs",
                            files={"file": (item["item_id"] + ".pdf", data, "application/pdf")},
                            data={"metadata_json": canonical(item["metadata"])})["job_id"]

    def poll(self, job_id):
        if not re.fullmatch(r"[a-f0-9]{32}", job_id):
            raise BatchError("Invalid document job identifier")
        return self.request("GET", "/document-jobs/" + job_id)


def code_identity():
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()
    return {"commit": git("rev-parse", "HEAD"), "branch": git("branch", "--show-current"),
            "dirty": bool(git("status", "--porcelain"))}


def apply(plan, payloads, output, api, *, job_timeout=900, poll_interval=1, backup_ref):
    """Fail closed on pending review; preserve the evidence of partial/unknown outcomes."""
    if plan.get("plan_sha256") != digest({k: v for k, v in plan.items() if k != "plan_sha256"}):
        raise BatchError("Fixed plan was modified")
    if any(i["review"]["status"] != "ready" for i in plan["items"]):
        raise BatchError("Review pending: prepare metadata before apply")
    if len(payloads) != len(plan["items"]) or any(
            hashlib.sha256(data).hexdigest() != item["sha256"]
            for item, data in zip(plan["items"], payloads)):
        raise BatchError("Payload does not match the fixed plan")
    if not backup_ref.strip():
        raise BatchError("Record the completed local backup reference")
    before = api.snapshot()
    if before["status"] != "ready":
        raise BatchError("Existing library must be ready before expansion")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "plan.json", plan)
    write_json(output / "before.json", before)
    journal = Journal(output / "events.jsonl")
    receipt = {"batch_id": plan["batch_id"], "plan_sha256": plan["plan_sha256"],
               "code": code_identity(), "backup_ref": backup_ref,
               "outcome": "running", "items": [], "manual_retrieval_review": "pending"}
    journal.add("batch_started", batch_id=plan["batch_id"], plan_sha256=plan["plan_sha256"])
    before_ids = {d["doc_id"] for d in before["documents"]}
    error = None
    try:
        for item, data in zip(plan["items"], payloads):
            row = {"item_id": item["item_id"], "sha256": item["sha256"], "outcome": "submission_unknown"}
            receipt["items"].append(row)
            journal.add("submission_started", item_id=item["item_id"], sha256=item["sha256"])
            job_id = api.submit(item, data)
            row.update(job_id=job_id, outcome="pending")
            journal.add("job_submitted", item_id=item["item_id"], job_id=job_id)
            deadline, last_stage = time.monotonic() + job_timeout, None
            while True:
                job = api.poll(job_id)
                stage = job["stage"]
                if stage != last_stage:
                    journal.add("job_stage", job_id=job_id, stage=stage)
                    last_stage = stage
                if stage == "error":
                    row.update(outcome="error", error_code=job["error"]["code"])
                    raise BatchError("Document job failed: " + job["error"]["code"])
                if stage == "done":
                    result, expected = job["result"], item["expected_doc_id"]
                    doc = result["document"]
                    if doc["doc_id"] != expected or doc["file_sha256"] != item["sha256"] or doc["status"] != "ready":
                        raise BatchError("Completed job violates file identity/ready contract")
                    row.update(outcome="already_present" if expected in before_ids else "imported",
                               doc_id=expected, index_version=result["index_version"],
                               page_count=doc["page_count"],
                               metadata_differences={k: {"requested": v, "stored": doc.get(k)}
                                                     for k, v in item["metadata"].items() if doc.get(k) != v})
                    journal.add("document_verified", **row)
                    break
                if time.monotonic() >= deadline:
                    row["outcome"] = "timeout_unknown"
                    raise BatchError("Job deadline exceeded; do not automatically resubmit")
                time.sleep(poll_interval)
        receipt["outcome"] = "completed"
    except Exception as exc:
        error = exc
        receipt["outcome"] = "incomplete"
        # Exception/provider messages and request contents are deliberately not serialized.
        journal.add("batch_interrupted", exception_type=type(exc).__name__)
    finally:
        try:
            after = api.snapshot()
            write_json(output / "after.json", after)
            after_ids = {d["doc_id"] for d in after["documents"]}
            receipt["document_delta"] = {"added": sorted(after_ids - before_ids),
                                         "removed": sorted(before_ids - after_ids)}
            expected_added = {r["doc_id"] for r in receipt["items"] if r["outcome"] == "imported"}
            receipt["collection_delta_verified"] = (
                receipt["outcome"] == "completed" and after_ids - before_ids == expected_added
                and not before_ids - after_ids
                and all(d["status"] == "ready" for d in after["documents"]
                        if d["doc_id"] in {i["expected_doc_id"] for i in plan["items"]}))
        except Exception as exc:
            receipt["collection_delta_verified"] = False
            receipt["after_snapshot_error"] = type(exc).__name__
        if not receipt["collection_delta_verified"] and error is None:
            receipt["outcome"] = "incomplete"
            error = BatchError("Collection delta was not verified; inspect receipt")
        journal.add("batch_finished", outcome=receipt["outcome"])
        receipt["last_event_sha256"] = journal.tail
        write_json(output / "receipt.json", receipt)
    if error is not None:
        raise BatchError("Batch incomplete; inspect saved receipt and local job status") from error
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply"))
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="New local output file (plan) or directory (apply)")
    parser.add_argument("--api", default="http://127.0.0.1:18000")
    parser.add_argument("--backup-ref", default="", help="Reference of a separately completed local backup")
    parser.add_argument("--plan", type=Path, help="Previously reviewed plan.json; required for apply")
    args = parser.parse_args()
    try:
        plan, payloads = prepare(args.manifest.resolve())
        if args.action == "plan":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(plan, ensure_ascii=False, indent=2) + "\n")
            print(f"Plan fixed: {plan['batch_id']}, {len(plan['items'])} unique files; no HTTP writes")
        else:
            if args.plan is None or json.loads(args.plan.read_text(encoding="utf-8-sig")) != plan:
                raise BatchError("Apply requires an unchanged, previously saved plan")
            receipt = apply(plan, payloads, args.output, LocalAPI(args.api), backup_ref=args.backup_ref)
            print(f"Batch {receipt['outcome']}; manual retrieval review pending")
    except BatchError as exc:
        parser.exit(1, f"Batch stopped: {exc}\n")
    except (ValueError, KeyError, TypeError, OSError):
        parser.exit(1, "Batch stopped. Inspect the local manifest/receipt; raw errors are not printed.\n")


if __name__ == "__main__":
    main()
