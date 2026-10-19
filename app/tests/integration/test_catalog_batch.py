"""Audit-tool gates and receipts, including real local document-job integration."""
import copy
from contextlib import nullcontext
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
import fitz

from tools import catalog_batch as batch


@pytest.fixture
def manifest(tmp_path, pdf):
    value = {"schema_version": 1, "batch_id": "COL-001-synthetic",
             "items": [{"item_id": "synthetic-01", "pdf_path": str(pdf),
                        "sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                        "metadata": {"title": "Synthetic accession", "year": 2024, "topics": ["自然科学"]},
                        "review": {"status": "ready", "method": "automated_pdf_check",
                                   "evidence": "synthetic fixture; not a literature review"}}]}
    path = tmp_path / "input.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path, value


def save_input(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def assert_chain(output):
    previous = "0" * 64
    events = [json.loads(line) for line in (output / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    for sequence, event in enumerate(events, 1):
        sha = event.pop("event_sha256")
        assert event["previous_sha256"] == previous and event["sequence"] == sequence
        assert batch.digest(event) == sha
        previous = sha
    receipt = json.loads((output / "receipt.json").read_text(encoding="utf-8"))
    assert receipt["last_event_sha256"] == previous
    return receipt


def test_plan_preserves_provenance_and_changes_without_local_path(manifest):
    path, raw = manifest
    raw["items"][0]["metadata_before"] = {"title": "Candidate title", "year": None}
    raw["items"][0]["metadata"]["source_url"] = "https://example.org/synthetic"
    save_input(path, raw)
    plan, payloads = batch.prepare(path)
    item = plan["items"][0]
    assert item["metadata_changes"]["year"] == {"before": None, "after": 2024}
    assert item["metadata"]["source_url"] == "https://example.org/synthetic"
    assert item["sha256"] == hashlib.sha256(payloads[0]).hexdigest()
    assert "pdf_path" not in batch.canonical(plan) and str(path.parent) not in batch.canonical(plan)


@pytest.mark.parametrize("problem", ["changed_bytes", "duplicate_content", "duplicate_id", "year_bool", "unknown_metadata", "bad_header"])
def test_invalid_batch_stops_before_upload(manifest, problem):
    path, raw = manifest
    row = raw["items"][0]
    if problem == "changed_bytes":
        row["sha256"] = "0" * 64
    elif problem.startswith("duplicate"):
        other = copy.deepcopy(row)
        other["item_id"] = "different-id" if problem == "duplicate_content" else row["item_id"]
        raw["items"].append(other)
    elif problem == "year_bool":
        row["metadata"]["year"] = True
    elif problem == "unknown_metadata":
        row["metadata"]["doc_id"] = "override"
    elif problem == "bad_header":
        pdf = path.parent / "bad.pdf"
        pdf.write_bytes(b"this is not a PDF")
        row.update(pdf_path=str(pdf), sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
    save_input(path, raw)
    with pytest.raises((batch.BatchError, ValueError)):
        batch.prepare(path)


@pytest.mark.parametrize("gate", ["pending", "modified_plan", "modified_payload", "missing_backup"])
def test_apply_gates_before_network(manifest, tmp_path, gate):
    path, raw = manifest
    if gate == "pending":
        raw["items"][0]["review"]["status"] = "pending"
        save_input(path, raw)
    plan, payloads = batch.prepare(path)
    if gate == "modified_plan":
        plan["items"][0]["metadata"]["title"] = "unreviewed change"
    if gate == "modified_payload":
        payloads = [b"changed"]
    api = Mock()
    with pytest.raises(batch.BatchError):
        batch.apply(plan, payloads, tmp_path / "out", api, backup_ref="" if gate == "missing_backup" else "fixture")
    api.snapshot.assert_not_called()
    api.submit.assert_not_called()


@pytest.mark.parametrize("url", ["https://example.org", "http://user:secret@localhost:18000", "http://localhost:18000/path"])
def test_only_local_origin_accepted(url):
    with pytest.raises(batch.BatchError):
        batch.LocalAPI(url)


def test_transport_errors_and_redirects_do_not_disclose_response():
    api = batch.LocalAPI("http://127.0.0.1:18000")
    for result in (requests.ConnectionError("sensitive upstream detail"), SimpleNamespace(status_code=302)):
        api.session.request = Mock(side_effect=result if isinstance(result, Exception) else None,
                                   return_value=result)
        with pytest.raises(batch.BatchError) as error:
            api.request("GET", "/health")
        assert "sensitive" not in str(error.value)
        assert api.session.request.call_args.kwargs["allow_redirects"] is False


@pytest.mark.parametrize("stage", ["error", "waiting", "transport", "submit_transport"])
def test_interrupted_batch_retains_job_and_receipt_without_retry(manifest, tmp_path, stage):
    path, _ = manifest
    plan, payloads = batch.prepare(path)
    api = Mock()
    api.snapshot.return_value = {"status": "ready", "documents": []}
    api.submit.return_value = "a" * 32
    api.poll.return_value = {"stage": stage, "error": {"code": "INVALID_PDF", "message": "not for receipt"}}
    if stage == "transport":
        api.poll.side_effect = requests.ConnectionError("do not copy server detail")
    if stage == "submit_transport":
        api.submit.side_effect = requests.ConnectionError("do not copy server detail")
    output = tmp_path / "out"
    with pytest.raises(batch.BatchError):
        batch.apply(plan, payloads, output, api, backup_ref="synthetic-fixture", job_timeout=0)
    receipt = assert_chain(output)
    assert receipt["outcome"] == "incomplete"
    if stage == "submit_transport":
        assert receipt["items"][0]["outcome"] == "submission_unknown"
        api.poll.assert_not_called()
    else:
        assert receipt["items"][0]["job_id"] == "a" * 32
    assert api.submit.call_count == 1
    assert "not for receipt" not in (output / "receipt.json").read_text()
    assert "do not copy server detail" not in (output / "events.jsonl").read_text()


@pytest.mark.parametrize("present", [False, True])
def test_apply_real_document_jobs_and_duplicate_receipt(client, imported, manifest, tmp_path, present):
    path, raw = manifest
    if not present:
        source = tmp_path / "new.pdf"
        with fitz.open() as pdf:
            pdf.new_page().insert_text((60, 90), "New accession test evidence.")
            pdf.save(source)
        raw["items"][0].update(pdf_path=str(source), sha256=hashlib.sha256(source.read_bytes()).hexdigest())
        save_input(path, raw)
    plan, payloads = batch.prepare(path)
    api = batch.LocalAPI("http://127.0.0.1:18000")

    def request(method, url, **kwargs):
        kwargs.pop("allow_redirects")
        kwargs.pop("timeout")
        return client.request(method, url, **kwargs)

    api.session.request = request
    output = tmp_path / "receipt"
    with pytest.warns(UserWarning, match="metadata") if present else nullcontext():
        result = batch.apply(plan, payloads, output, api, backup_ref="synthetic-only", poll_interval=0.01)
    receipt = assert_chain(output)
    assert result == receipt and result["collection_delta_verified"] is True
    assert result["items"][0]["outcome"] == ("already_present" if present else "imported")
    if present:
        assert result["items"][0]["metadata_differences"]["title"]["stored"] == imported["document"]["title"]
    else:
        assert result["items"][0]["metadata_differences"] == {}
    assert result["document_delta"] == {"added": [] if present else [plan["items"][0]["expected_doc_id"]], "removed": []}
    assert result["manual_retrieval_review"] == "pending"
    assert str(path.parent) not in (output / "plan.json").read_text(encoding="utf-8")
    with pytest.raises(FileExistsError):
        batch.apply(plan, payloads, output, api, backup_ref="synthetic-only")


@pytest.mark.parametrize("problem", ["concurrent_import", "after_unavailable"])
def test_final_snapshot_failure_cannot_claim_verified_batch(manifest, tmp_path, problem):
    path, _ = manifest
    plan, payloads = batch.prepare(path)
    item = plan["items"][0]
    doc = {**item["metadata"], "doc_id": item["expected_doc_id"], "file_sha256": item["sha256"],
           "status": "ready", "page_count": 2}
    api = Mock()
    after = {"status": "ready", "documents": [doc, {"doc_id": "d_other", "status": "ready"}]}
    api.snapshot.side_effect = [{"status": "ready", "documents": []},
                               OSError("private detail") if problem == "after_unavailable" else after]
    api.submit.return_value = "a" * 32
    api.poll.return_value = {"stage": "done", "result": {"document": doc, "index_version": "idx_fixture"}}
    output = tmp_path / "out"
    with pytest.raises(batch.BatchError):
        batch.apply(plan, payloads, output, api, backup_ref="fixture")
    result = assert_chain(output)
    assert result["outcome"] == "incomplete" and result["collection_delta_verified"] is False
