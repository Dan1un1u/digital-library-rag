"""MQ-003: years describe the collected version under the revised requirement."""
import copy

import pytest

from dlrag.ingestion.metadata_api import merge_candidates, PROMPT
from dlrag.ingestion.metadata_year import validate_year


def output(year=None, source=None):
    return {"metadata": {"year": year}, "field_sources": {"year": source} if source else {}, "warnings": []}


def candidate(year, excerpt, kind="publication", page=1):
    row = {"value": year, "pdf_page": page, "excerpt": excerpt}
    if kind is not None:
        row["date_type"] = kind
    return row


@pytest.mark.parametrize("excerpt,kind", [
    ("17 Feb 2023", None),
    ("17 Feb 2023", "publication"),
])
def test_unlabelled_date_needs_a_version_context(excerpt, kind):
    source, reason = validate_year(candidate(2023, excerpt, kind), [{"text": excerpt}])
    assert source is None and reason == "missing_version_context"


@pytest.mark.parametrize("excerpt,kind", [
    ("arXiv:2111.13824v4 [cs.CV] 17 Feb 2023", None),
    ("Revised on 17 Feb 2023", "revision"),
    ("Submitted 17 Feb 2023", "submission"),
    ("Accepted on 17 Feb 2023", "acceptance"),
    ("This preprint was published on 17 Feb 2023", "preprint"),
    ("This preprint was published on 17 Feb 2023", "publication"),
    ("Published on arXiv 17 Feb 2023", "publication"),
])
def test_explicit_manuscript_dates_can_supply_collected_version_year(excerpt, kind):
    result = output()
    count = merge_candidates(result, {"year": candidate(2023, excerpt, kind)}, [{"text": excerpt}])
    assert count == 1 and result["metadata"]["year"] == 2023
    assert result["year_review"]["status"] == "candidate_supported"
    assert result["field_sources"]["year"]["date_type"] != "publication"


@pytest.mark.parametrize("text,year,kind", [
    ("Published in 2024", 2024, "publication"),
    ("Published as a conference paper at ICLR 2025", 2025, "publication"),
    ("37th Conference on Neural Information Processing Systems (NeurIPS 2023).", 2023, "publication"),
    ("Proceedings of the 38th International Conference on Machine Learning, PMLR 139, 2021.", 2021, "publication"),
    ("© 2025 Copyright held by the owner/author(s).", 2025, "copyright"),
    ("发表年份：2022", 2022, "publication"),
])
def test_explicit_publication_evidence_remains_accepted(text, year, kind):
    result = output()
    assert merge_candidates(result, {"year": candidate(year, text, kind)}, [{"text": text}]) == 1
    assert result["metadata"]["year"] == year
    assert result["field_sources"]["year"]["grounding"] == "page_text"


def test_current_revision_takes_priority_over_another_publication_stage():
    text = "Published in 2022. Revised 17 Feb 2023."
    rejected = output()
    merge_candidates(rejected, {"year": candidate(2022, "Published in 2022")}, [{"text": text}])
    assert rejected["metadata"]["year"] is None
    supported = output()
    merge_candidates(supported, {"year": candidate(2023, "Revised 17 Feb 2023")}, [{"text": text}])
    assert supported["metadata"]["year"] == 2023
    assert supported["field_sources"]["year"]["date_type"] == "revision"


@pytest.mark.parametrize("page_text", [
    "arXiv:2111.13824v4 17 Feb 2023",
    "Title and authors\nReferences\nPublished in 2023",
])
def test_model_cannot_invent_publication_phrase_or_use_reference_section(page_text):
    result = output()
    merge_candidates(result, {"year": candidate(2023, "Published in 2023")}, [{"text": page_text}])
    assert result["metadata"]["year"] is None
    assert result["year_review"]["reason"] == "excerpt_not_on_page"


def test_copyright_symbol_cannot_be_fabricated_to_justify_bare_revision_year():
    result = output()
    merge_candidates(result, {"year": candidate(2023, "© 2023", "copyright")},
                     [{"text": "arXiv:2111.13824v4 17 Feb 2023"}])
    assert result["metadata"]["year"] is None
    assert result["year_review"]["reason"] == "excerpt_not_on_page"


def test_conflicting_publication_dates_request_review():
    text = "Published in 2022. Published online in 2023."
    result = output()
    merge_candidates(result, {"year": candidate(2023, text)}, [{"text": text}])
    assert result["metadata"]["year"] is None
    assert result["year_review"]["reason"] == "conflicting_version_years"


def test_image_only_publication_evidence_is_marked_as_model_reported():
    result = output()
    merge_candidates(result, {"year": candidate(2024, "Published in 2024")}, [{"text": "", "image": "data:image/jpeg;base64,fixture"}])
    assert result["metadata"]["year"] == 2024
    assert result["year_review"]["grounding"] == "model_read_page_image"


def test_server_evidence_can_use_publication_footer_beyond_model_text_preview():
    excerpt = "Proceedings of ICML, PMLR 139, 2021."
    text = "Abstract and body. " * 500 + excerpt
    result = output()
    merge_candidates(result, {"year": candidate(2021, excerpt)},
                     [{"text": text[:6000], "validation_text": text, "image": "page-image"}])
    assert result["metadata"]["year"] == 2021
    assert result["year_review"]["grounding"] == "page_text"


def test_rejected_year_does_not_discard_supported_title():
    text = "Evidence Search for Libraries\narXiv:2111.13824v4 17 Feb 2023"
    rows = {"title": {"value": "Evidence Search for Libraries", "pdf_page": 1, "excerpt": "Evidence Search for Libraries"},
            "year": candidate(2022, "17 Feb 2023")}
    result = output()
    original = copy.deepcopy(rows)
    assert merge_candidates(result, rows, [{"text": text}]) == 1
    assert result["metadata"]["title"] == "Evidence Search for Libraries" and result["metadata"]["year"] is None
    assert rows == original


def test_invalid_enhanced_year_cannot_leave_unverified_seed_value():
    result = output(2023, {"method": "pdf_metadata", "pdf_page": 1, "excerpt": "17 Feb 2023"})
    merge_candidates(result, {"year": None}, [{"text": "17 Feb 2023"}])
    assert result["metadata"]["year"] is None and "year" not in result["field_sources"]


def test_rejected_api_year_can_retain_separately_grounded_publication_seed():
    result = output(2022, {"method": "document_date_candidate", "pdf_page": 1, "excerpt": "Published in 2022"})
    text = "Published in 2022."
    assert merge_candidates(result, {"year": candidate(2023, "Invented date 2023")}, [{"text": text}]) == 0
    assert result["metadata"]["year"] == 2022
    assert result["year_review"]["source"] == "validated_seed"


@pytest.mark.parametrize("row", [
    candidate(True, "Published in 2023"),
    candidate(9999, "Published in 9999"),
    candidate(2023, "Published in 2023", page=2),
    candidate(2023, "Published in 2023", kind=[]),
])
def test_malformed_year_candidates_are_rejected_without_crashing(row):
    source, reason = validate_year(row, [{"text": "Published in 2023"}])
    assert source is None and reason == "invalid_candidate"


def test_prompt_explicitly_requires_date_semantics_and_no_arxiv_year_guess():
    assert 'date_type="version"' in PROMPT
    assert "修订日期" in PROMPT and "不得从 arXiv 编号推算年份" in PROMPT
    assert "不要求正式发表" in PROMPT


@pytest.mark.parametrize("text,excerpt", [
    ("Submitted to ICLR 2025", "ICLR 2025"),
    ("Under review as a conference paper at ICLR 2025", "conference paper at ICLR 2025"),
    ("Not published in 2025.", "published in 2025"),
    ("Not yet published in 2025.", "published in 2025"),
    ("Not published in 2025.", "Not published in 2025."),
])
def test_conference_targets_and_negation_do_not_supply_a_version_date(text, excerpt):
    result = output(2025, {"method": "document_date_candidate", "pdf_page": 1, "excerpt": excerpt})
    merge_candidates(result, {"year": candidate(2025, excerpt)}, [{"text": text}])
    assert result["metadata"]["year"] is None  # Also checks the seed bypass.


def test_trimmed_preprint_quote_keeps_document_context():
    source, _ = validate_year(candidate(2023, "published in 2023"),
                              [{"text": "This preprint was published in 2023."}])
    assert source["date_type"] == "preprint"
    assert "preprint" in source["context"]


def test_revision_on_second_page_blocks_older_first_page_publication_year():
    pages = [{"text": "Published in 2022"}, {"text": "Revised in 2023"}]
    assert validate_year(candidate(2022, "Published in 2022"), pages)[0] is None
    assert validate_year(candidate(2023, "Revised in 2023", page=2), pages)[0]["value"] == 2023


def test_version_date_does_not_come_from_arxiv_identifier():
    source, _ = validate_year(candidate(2023, "arXiv:2301.12345v4"), [{"text": "arXiv:2301.12345v4"}])
    assert source is None


def test_published_file_uses_publication_date_instead_of_submission_history():
    text = "Received in 2022. Accepted in 2023. Published in 2024."
    assert validate_year(candidate(2024, "Published in 2024"), [{"text": text}])[0]["value"] == 2024
    assert validate_year(candidate(2023, "Accepted in 2023"), [{"text": text}])[0] is None


def test_chinese_revision_date_is_supported():
    text = "修订日期：2023年2月17日"
    source, _ = validate_year(candidate(2023, text, "revision"), [{"text": text}])
    assert source["value"] == 2023 and source["date_type"] == "revision"
