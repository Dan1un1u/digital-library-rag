"""Journal issue date survives the preview/import boundary and lookup differences."""
import json

import fitz
from pydantic import SecretStr
import pytest


@pytest.mark.parametrize("lookup", [False, True])
def test_issue_year_survives_preview_lookup_and_import(client, services, monkeypatch, lookup):
    services.settings.app_mode = "real"
    services.settings.siliconflow_api_key = SecretStr("synthetic-test-key")
    title = "Evidence for Library Metadata"
    header = "Library Research Quarterly\n2009\nVolume 3 Number 4"
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((40, 60), header)
        page.insert_text((40, 130), title, fontsize=15)
        page.insert_text((40, 170), "Alice Smith")
        raw = pdf.tobytes()
    reply = {"title": {"value": title, "pdf_page": 1, "excerpt": title},
             "authors": {"value": ["Alice Smith"], "pdf_page": 1, "excerpt": "Alice Smith"},
             "year": {"value": 2009, "pdf_page": 1, "excerpt": header, "date_type": "issue"}}
    monkeypatch.setattr("dlrag.ingestion.metadata_api.request_candidates", lambda *a: reply)
    record = {"title": [title], "author": [{"given": "Alice", "family": "Smith"}],
              "DOI": "10.1234/library", "type": "journal-article", "published-online": {"date-parts": [[2010, 3, 20]]}}
    monkeypatch.setattr("dlrag.ingestion.bibliography.query_crossref", lambda *a: [record])
    response = client.post("/documents/metadata", files={"file": ("fixture.pdf", raw, "application/pdf")},
                           data={"use_lookup": str(lookup).lower()})
    result = response.json()
    assert response.status_code == 200 and result["metadata"]["year"] == 2009
    assert result["field_sources"]["year"]["date_type"] == "issue"
    if lookup:
        assert result["bibliographic_enrichment"]["candidates"][0]["selected_date"]["year"] == 2010
        assert "year" not in result["bibliographic_enrichment"]["filled_fields"]
    services.settings.app_mode = "mock"
    imported = client.post("/documents", files={"file": ("fixture.pdf", raw, "application/pdf")},
                           data={"metadata_json": json.dumps(result["metadata"])})
    assert imported.status_code == 200 and imported.json()["document"]["year"] == 2009
