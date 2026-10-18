"""Regression for the in-scope enhanced-recognition finding MQ-003.

Synthetic inputs reproduce the relevant decision without shipping user PDFs or
calling a model. The original xfail is now an ordinary regression assertion.
MQ-001/MQ-002 are local-only observations excluded by the user's project scope;
their original evidence remains in Git history and metadata-findings.md.
"""
from dlrag.ingestion.metadata_api import merge_candidates


def test_mq003_revision_date_alone_is_not_a_publication_year():
    result = {"metadata": {"year": None}, "field_sources": {}}
    excerpt = "17 Feb 2023"  # Exact evidence excerpt in the original enhanced result.
    merge_candidates(result, {"year": {"value": 2023, "pdf_page": 1, "excerpt": excerpt}},
                     [{"pdf_page": 1, "text": "arXiv:2111.13824v4 [cs.CV] " + excerpt}])
    # The supplied page has no publication-year statement. Keep it unknown;
    # a separate authoritative record is needed to establish the formal year.
    assert result["metadata"]["year"] is None
    assert result["year_review"]["status"] == "needs_confirmation"
