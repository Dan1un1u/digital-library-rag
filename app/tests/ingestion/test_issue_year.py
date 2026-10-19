"""MQ-005: retain a year grounded in the collected journal issue header."""
from dlrag.ingestion.metadata_api import merge_candidates
import pytest

HEADER = "DHQ: Digital Humanities Quarterly\n2009\nVolume 3 Number 4"


def test_issue_header_year_is_retained_instead_of_discarded():
    result = {"metadata": {"year": None}, "field_sources": {}, "warnings": []}
    merge_candidates(result, {"year": {"value": 2009, "pdf_page": 1, "excerpt": HEADER, "date_type": "publication"}},
                     [{"text": HEADER}])
    assert result["metadata"]["year"] == 2009
    assert result["field_sources"]["year"]["date_type"] == "issue"


@pytest.mark.parametrize("header", [
    "A Journal of Library Research\n2009\nVol. 3 No. 4",
    "数字图书馆学报\n2009\n第3卷第4期",
])
def test_other_issue_headers_can_date_the_collected_version(header):
    result = {"metadata": {"year": None}, "field_sources": {}}
    merge_candidates(result, {"year": {"value": 2009, "pdf_page": 1, "excerpt": header}}, [{"text": header}])
    assert result["metadata"]["year"] == 2009


@pytest.mark.parametrize("prefix", ["Title\nReferences\n", "Title\nAbstract\n", "Title\nIntroduction\n", "body\n" * 500])
def test_issue_like_citation_after_front_matter_is_not_a_document_date(prefix):
    result = {"metadata": {"year": None}, "field_sources": {}}
    merge_candidates(result, {"year": {"value": 2009, "pdf_page": 1, "excerpt": HEADER}}, [{"text": prefix + HEADER}])
    assert result["metadata"]["year"] is None


def test_current_revision_still_takes_priority_over_issue_history():
    text = HEADER + "\nRevised in 2011"
    result = {"metadata": {"year": None}, "field_sources": {}}
    merge_candidates(result, {"year": {"value": 2009, "pdf_page": 1, "excerpt": HEADER}}, [{"text": text}])
    assert result["metadata"]["year"] is None
