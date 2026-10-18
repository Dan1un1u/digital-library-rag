"""Unfixed findings from COL-001-20261018-P01; expected failures are not passes.

Synthetic inputs reproduce the relevant decision without shipping user PDFs or
calling a model. strict=True requires a deliberate status update after a fix.
"""
import pytest

from dlrag.ingestion.metadata import author_names
from dlrag.ingestion.metadata_api import merge_candidates


@pytest.mark.xfail(strict=True, reason="MQ-001: organization accepted as person on local metadata path")
def test_mq001_organization_is_not_an_author():
    assert author_names("MEGVII Technology") == []


@pytest.mark.xfail(strict=True, reason="MQ-003: arXiv revision date accepted as publication year")
def test_mq003_revision_date_alone_is_not_a_publication_year():
    result = {"metadata": {"year": None}, "field_sources": {}}
    excerpt = "arXiv:2111.13824v4 [cs.CV] 17 Feb 2023"
    merge_candidates(result, {"year": {"value": 2023, "pdf_page": 1, "excerpt": excerpt}},
                     [{"pdf_page": 1, "text": excerpt}])
    # The supplied page has no publication-year statement. Keep it unknown;
    # a separate authoritative record is needed to establish the formal year.
    assert result["metadata"]["year"] is None
