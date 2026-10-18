"""In-scope enhanced-recognition finding; expected failures are not passes.

Synthetic inputs reproduce the relevant decision without shipping user PDFs or
calling a model. strict=True requires a deliberate status update after a fix.
MQ-001/MQ-002 are local-only observations excluded by the user's project scope;
their original evidence remains in Git history and metadata-findings.md.
"""
import pytest

from dlrag.ingestion.metadata_api import merge_candidates


@pytest.mark.xfail(strict=True, reason="MQ-003: arXiv revision date accepted as publication year")
def test_mq003_revision_date_alone_is_not_a_publication_year():
    result = {"metadata": {"year": None}, "field_sources": {}}
    excerpt = "arXiv:2111.13824v4 [cs.CV] 17 Feb 2023"
    merge_candidates(result, {"year": {"value": 2023, "pdf_page": 1, "excerpt": excerpt}},
                     [{"pdf_page": 1, "text": excerpt}])
    # The supplied page has no publication-year statement. Keep it unknown;
    # a separate authoritative record is needed to establish the formal year.
    assert result["metadata"]["year"] is None
