"""MQ-005: retain a year grounded in the collected journal issue header."""
from dlrag.ingestion.metadata_api import merge_candidates

HEADER = "DHQ: Digital Humanities Quarterly\n2009\nVolume 3 Number 4"


def test_issue_header_year_is_retained_instead_of_discarded():
    result = {"metadata": {"year": None}, "field_sources": {}, "warnings": []}
    merge_candidates(result, {"year": {"value": 2009, "pdf_page": 1, "excerpt": HEADER, "date_type": "publication"}},
                     [{"text": HEADER}])
    assert result["metadata"]["year"] == 2009
    assert result["field_sources"]["year"]["date_type"] == "issue"
