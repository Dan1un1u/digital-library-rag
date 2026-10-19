"""Replay PR1's earlier acceptance examples using the collected-version policy.

Uses synthetic PDFs and stub model replies through the real preview endpoint.
Protected running libraries are read only; no real model/lookup/index call runs.
"""
import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

import fitz
from fastapi.testclient import TestClient
from pydantic import SecretStr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dlrag.api.main import create_app
from dlrag.ingestion.metadata_year import POLICY, validate_year
from dlrag.shared.config import Settings
from tools.catalog_batch import LocalAPI, code_identity, digest

SCENARIOS = [
    ("submitted_conference", "Submitted to ICLR 2025", "Submitted to ICLR 2025", 2025, None, None),
    ("under_review_conference", "Under review as a conference paper at ICLR 2025",
     "Under review as a conference paper at ICLR 2025", 2025, None, None),
    ("trimmed_preprint", "This preprint was published in 2023.", "published in 2023", 2023, 2023, "preprint"),
    ("full_negation_control", "Not published in 2024.", "Not published in 2024.", 2024, None, None),
    ("trimmed_negation", "Not published in 2024.", "published in 2024", 2024, None, None),
    ("formal_publication_control", "Published as a conference paper at ICLR 2025",
     "Published as a conference paper at ICLR 2025", 2025, 2025, "publication"),
    ("original_revision_control", "arXiv v4 17 Feb 2023", "17 Feb 2023", 2023, 2023, "version"),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protected-api", action="append")
    args = parser.parse_args()
    import dlrag
    assert Path(next(iter(dlrag.__path__))).resolve() == ROOT / "app/src/dlrag"
    identity = code_identity()
    if identity["dirty"]:
        parser.error("Acceptance review requires a clean commit")
    args.output.mkdir(parents=True, exist_ok=False)
    protected = {url: LocalAPI(url) for url in (args.protected_api or ["http://127.0.0.1:18000"])}
    before = {url: api.snapshot() for url, api in protected.items()}
    report = {"work_item": "PR1-VERSION-YEAR-ACCEPTANCE", "policy": POLICY, "code": identity,
              "created_at": datetime.now(timezone.utc).isoformat(), "source_path_verified": True,
              "scope": "synthetic PDF/API replay; no live model or registry; not a real-PDF accuracy estimate",
              "source_sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in [
                  "app/src/dlrag/ingestion/metadata_year.py", "app/src/dlrag/ingestion/metadata_api.py",
                  "app/src/dlrag/ingestion/bibliography.py", "app/src/dlrag/ui/app.py"]}, "cases": []}
    try:
        with tempfile.TemporaryDirectory(dir=args.output) as tmp:
            settings = Settings(app_mode="real", data_dir=Path(tmp) / "library",
                                siliconflow_api_key=SecretStr("synthetic-review-key"), _env_file=None)
            with TestClient(create_app(settings=settings)) as client:
                for ident, text, excerpt, year, expected, kind in SCENARIOS:
                    row = {"value": year, "pdf_page": 1, "excerpt": excerpt, "date_type": "publication"}
                    source, reason = validate_year(row, [{"text": text}])
                    with fitz.open() as pdf:
                        page = pdf.new_page()
                        page.insert_text((45, 65), "Acceptance Audit Fixture", fontsize=18)
                        page.insert_text((45, 110), "Alice Smith")
                        page.insert_text((45, 160), text)
                        payload = pdf.tobytes()
                    reply = {"title": {"value": "Acceptance Audit Fixture", "pdf_page": 1,
                                       "excerpt": "Acceptance Audit Fixture"}, "year": row}
                    with patch("dlrag.ingestion.metadata_api.request_candidates", return_value=copy.deepcopy(reply)), \
                         patch("dlrag.ingestion.bibliography.query_crossref", side_effect=AssertionError("No lookup")):
                        response = client.post("/documents/metadata", files={"file": ("fixture.pdf", payload, "application/pdf")},
                                               data={"use_api": "true", "use_lookup": "false"})
                    response.raise_for_status()
                    result = response.json()
                    actual = result["metadata"]["year"]
                    date_kind = result["field_sources"].get("year", {}).get("date_type")
                    report["cases"].append({"case_id": ident, "page_text": text, "candidate": row,
                        "expected_year": expected, "actual_year": actual, "expected_date_type": kind,
                        "actual_date_type": date_kind, "function_reason": reason,
                        "year_review": result["year_review"], "http_status": response.status_code,
                        "passed": actual == expected and date_kind == kind and (source is not None) == (expected is not None)})
                assert client.get("/documents?include_nonready=true").json()["documents"] == []
                assert client.get("/health").json()["manifest"] is None
                report["preview_did_not_import"] = True
    finally:
        report["protected_libraries_unchanged"] = before == {url: api.snapshot() for url, api in protected.items()}
        report["protected_snapshot_sha256"] = {url: digest(s) for url, s in before.items()}
        report["worktree_dirty_after"] = code_identity()["dirty"]
        report["passed"] = (len(report["cases"]) == len(SCENARIOS) and all(r["passed"] for r in report["cases"])
                            and report.get("preview_did_not_import", False) and report["protected_libraries_unchanged"]
                            and not report["worktree_dirty_after"])
        (args.output / "review.json").write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode())
    print(json.dumps({"cases": len(report["cases"]), "passed": report["passed"], "code": identity}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
