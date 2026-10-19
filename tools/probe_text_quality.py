"""Read-only corpus scan and isolated real-PDF ingestion checks for ING-002."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

from fastapi.testclient import TestClient
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlrag.api.main import create_app
from dlrag.ingestion.fulltext import REVIEW_DIAGNOSTIC
from dlrag.ingestion.parser import parse_pdf
from dlrag.ingestion.text_quality import DIAGNOSTIC, encoding_evidence
from dlrag.shared.config import Settings
from tools.catalog_batch import LocalAPI, code_identity, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    import dlrag
    assert Path(next(iter(dlrag.__path__))).resolve() == ROOT / "app/src/dlrag"
    identity = code_identity()
    if identity["dirty"]:
        parser.error("Commit the tested source first")
    args.output.mkdir(parents=True, exist_ok=False)
    catalog = json.loads((ROOT / "docs/validation/COL-002/catalog.json").read_text())["items"]
    candidates = [p for folder in ("pdfs", "derived") for p in (args.pdf_root / folder).glob("*.pdf")]
    by_hash = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in candidates}
    protected = {p: LocalAPI("http://127.0.0.1:" + str(p)) for p in [18000, 19000, 19010]}
    before = {p: api.snapshot() for p, api in protected.items()}
    report = {"code": identity, "scope": "50 actual import-file read-only scans; isolated TestClient jobs; mock vectors, no live LLM/OCR",
              "corpus_scan": [], "jobs": [], "passed": False}
    try:
        for item in catalog:
            path = by_hash[item["import_sha256"]]
            pages = parse_pdf(path)
            report["corpus_scan"].append({"item_id": item["item_id"], "sha256": item["import_sha256"],
                "pages": len(pages), "encoding_suspect_pages": [p["pdf_page"] for p in pages if DIAGNOSTIC in p["diagnostics"]],
                "scan_suspect_pages": [p["pdf_page"] for p in pages if REVIEW_DIAGNOSTIC in p["diagnostics"]],
                "encoding_metrics": {str(p["pdf_page"]): encoding_evidence(p["raw_text"]) for p in pages
                                     if DIAGNOSTIC in p["diagnostics"]}})
        flagged = [r["item_id"] for r in report["corpus_scan"] if r["encoding_suspect_pages"]]
        assert flagged == ["HU08"], flagged
        assert next(r for r in report["corpus_scan"] if r["item_id"] == "HU08")["encoding_suspect_pages"] == list(range(1, 17))
        with tempfile.TemporaryDirectory(dir=args.output) as tmp:
            settings = Settings(app_mode="mock", data_dir=Path(tmp) / "library", _env_file=None)
            with TestClient(create_app(settings), raise_server_exceptions=False) as client:
                for ident in ["HU11", "HU08", "HU08"]:
                    item = next(r for r in catalog if r["item_id"] == ident)
                    path = by_hash[item["import_sha256"]]
                    old = client.get("/health").json()["manifest"]
                    response = client.post("/documents/jobs", files={"file": (path.name, path.read_bytes(), "application/pdf")},
                                           data={"metadata_json": json.dumps({"title": item["title"], "authors": item["authors"]})})
                    job_id = response.json()["job_id"]
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        job = client.get("/document-jobs/" + job_id).json()
                        if job["stage"] in {"done", "error"}:
                            break
                        time.sleep(.02)
                    assert job["stage"] == ("done" if ident == "HU11" else "error")
                    if ident == "HU08":
                        assert job["error"]["code"] == "TEXT_LAYER_REVIEW_REQUIRED"
                        assert client.get("/health").json()["manifest"] == old
                    report["jobs"].append({"item_id": ident, "sha256": item["import_sha256"], "stage": job["stage"],
                                           "error": job.get("error"), "passed": True})
                service = client.app.state.services
                item = next(r for r in catalog if r["item_id"] == "HU08")
                doc_id = "d_" + item["import_sha256"]
                assert service.library.get_page(doc_id, 1) is None
                assert not any(c["doc_id"] == doc_id for c in service.library.list_chunks(include_indexing=True))
                report["bad_document_excluded"] = True
        report["passed"] = True
    finally:
        report["protected_libraries_unchanged"] = before == {p: api.snapshot() for p, api in protected.items()}
        report["protected_snapshot_sha256"] = {str(p): digest(s) for p, s in before.items()}
        report["worktree_dirty_after"] = code_identity()["dirty"]
        report["passed"] = report["passed"] and report["protected_libraries_unchanged"] and not report["worktree_dirty_after"]
        (args.output / "result.json").write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"passed": report["passed"], "scanned": len(report["corpus_scan"]), "jobs": len(report["jobs"])}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
