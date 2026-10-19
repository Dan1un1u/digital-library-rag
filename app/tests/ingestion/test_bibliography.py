"""Deterministic bibliographic matching and failure tests; no network calls."""
import copy
from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from dlrag.ingestion import bibliography as module

TITLE = "Evidence Search: Reliable Metadata for Libraries"
AUTHORS = ["Alice Smith", "Bob Jones"]


def record(**changes):
    return {"title": [TITLE], "author": [{"given": "Alice", "family": "Smith"},
            {"given": "Bob", "family": "Jones"}], "DOI": "10.1234/Library.1",
            "type": "journal-article", "published-print": {"date-parts": [[2024, 11]]}, **changes}


def preview(**changes):
    return {"metadata": {"title": TITLE, "authors": AUTHORS.copy(), "year": None,
                         "source_url": None, **changes}, "field_sources": {},
            "warnings": ["版本年份待核对：无页面日期证据"], "requires_confirmation": True,
            "document_version": {"kind": "publication", "dois": ["10.1234/library.1"]}}


def enrich(monkeypatch, result, records):
    monkeypatch.setattr(module, "query_crossref", lambda *args: copy.deepcopy(records))
    module.enrich_metadata(result, SimpleNamespace(metadata_lookup_timeout_seconds=3))
    return result["bibliographic_enrichment"]


def test_unique_record_fills_only_missing_fields_with_date_provenance(monkeypatch):
    result = preview()
    audit = enrich(monkeypatch, result, [record()])
    assert result["metadata"]["year"] == 2024
    assert result["metadata"]["source_url"] == "https://doi.org/10.1234/library.1"
    assert set(audit["filled_fields"]) == {"year", "source_url"}
    assert result["field_sources"]["year"]["date_type"] == "published-print"
    assert result["year_review"]["source"] == "crossref"
    assert result["requires_confirmation"]
    assert not any(w.startswith("版本年份待核对") for w in result["warnings"])


@pytest.mark.parametrize("existing", [{"source_url": "https://arxiv.org/abs/2604.03298"},
                                      {"year": 2023}, {"source_url": "https://doi.org/10.1234/old"}])
def test_existing_fields_are_preserved_and_conflicts_visible(monkeypatch, existing):
    result = preview(**existing)
    audit = enrich(monkeypatch, result, [record()])
    assert all(result["metadata"][k] == v for k, v in existing.items())
    assert bool(audit["conflicts"]) == ("year" in existing or "doi.org" in existing.get("source_url", ""))
    assert not set(existing) & set(audit["filled_fields"])


def test_online_and_print_dates_stay_distinct_and_earliest_publication_selected():
    dates, chosen = module.publication_dates(record(**{
        "published-online": {"date-parts": [[2023, 12, 1]]},
        "published": {"date-parts": [[2020]]}, "created": {"date-parts": [[2019]]}}))
    assert len(dates) == 3
    assert chosen == {"kind": "published-online", "date_parts": [2023, 12, 1], "year": 2023}


@pytest.mark.parametrize("parts", [[[True]], [[9999]], [[datetime.now().year + 2]],
                                  [[2024, 13]], [[2024, 2, 30]], [[2024], [2025]], "2024", [[]]])
def test_bad_publication_dates_are_not_used(parts):
    assert module.publication_dates(record(**{"published-print": {"date-parts": parts}})) == ([], None)


def test_created_issued_accepted_and_preprint_dates_cannot_fill_publication_year(monkeypatch):
    row = record(**{"published-print": None, "created": {"date-parts": [[2026]]},
                    "issued": {"date-parts": [[2026]]}, "accepted": {"date-parts": [[2026]]}})
    result = preview()
    audit = enrich(monkeypatch, result, [row])
    assert result["metadata"]["year"] is None
    assert audit["filled_fields"] == ["source_url"]
    assert any("版本年份继续留空" in w for w in result["warnings"])


@pytest.mark.parametrize("change", [
    {"title": ["Evidence Search: An Unrelated Paper"]},
    {"author": [{"given": "Other", "family": "Smith"}, {"given": "Bob", "family": "Jones"}]},
    {"author": [{"given": "Alice", "family": "Smith"}]},
    {"author": None}, {"author": [{"name": "Anonymous Group"}]},
    {"DOI": "10.1234/library?key=secret"}, {"DOI": "https://localhost/secret"},
    {"type": "posted-content"}, {"title": None}, {"subtitle": [42]},
])
def test_wrong_or_unsupported_records_cannot_fill_fields(monkeypatch, change):
    result = preview()
    before = copy.deepcopy(result["metadata"])
    audit = enrich(monkeypatch, result, [record(**change)])
    assert result["metadata"] == before and audit["status"] == "no_match"


def test_subtitle_and_unicode_formatting_can_match_but_are_not_ignored(monkeypatch):
    row = record(title=["Evidence Search"], subtitle=["Reliable Metadata for Libraries"])
    result = preview(title=TITLE.replace(":", "："))
    assert enrich(monkeypatch, result, [row])["status"] == "completed"
    assert module.match_record(record(title=["Evidence Search"], subtitle=["Other Topic"]), TITLE, AUTHORS) is None


@pytest.mark.parametrize("duplicate", [True, False])
def test_duplicate_and_ambiguous_records_are_distinguished(monkeypatch, duplicate):
    rows = [record(), record(**({} if duplicate else {"DOI": "10.1234/other"}))]
    result = preview()
    audit = enrich(monkeypatch, result, rows)
    assert audit["status"] == ("completed" if duplicate else "ambiguous")
    assert (result["metadata"]["year"] is None) is (not duplicate)


@pytest.mark.parametrize("changes", [{"title": None}, {"authors": []}, {"authors": [None]},
                                    {"year": 2024, "source_url": "https://doi.org/10.1234/known"}])
def test_no_query_without_identity_or_missing_fields(monkeypatch, changes):
    def unexpected(*args):
        pytest.fail("network lookup must not run")
    monkeypatch.setattr(module, "query_crossref", unexpected)
    result = preview(**changes)
    module.enrich_metadata(result, SimpleNamespace(metadata_lookup_timeout_seconds=3))
    assert result["bibliographic_enrichment"]["status"] in {"insufficient_identity", "not_needed"}


def transport(monkeypatch, status=200, body=None):
    session = MagicMock()
    session.__enter__.return_value = session
    response = MagicMock()
    response.__enter__.return_value = response
    response.status_code = status
    response.iter_content.return_value = [body if body is not None else json.dumps({"message": {"items": [record()]}}).encode()]
    session.get.return_value = response
    monkeypatch.setattr(module.requests, "Session", lambda: session)
    return session


def test_transport_uses_fixed_endpoint_bounded_fields_and_no_credentials(monkeypatch):
    session = transport(monkeypatch)
    assert module.query_crossref(TITLE, AUTHORS + ["Carol Young"], 4) == [record()]
    args, kwargs = session.get.call_args
    assert args == (module.ENDPOINT,)
    assert session.trust_env is False
    assert kwargs["allow_redirects"] is False and kwargs["stream"] is True
    assert kwargs["params"]["rows"] == 5
    assert kwargs["params"]["query.bibliographic"] == TITLE + " " + " ".join(AUTHORS)
    assert "headers" not in kwargs and "auth" not in kwargs
    assert kwargs["timeout"] == (3, 4)


@pytest.mark.parametrize("failure,expected", [(429, "RATE_LIMIT"), (302, "HTTP_ERROR"), (503, "HTTP_ERROR"),
    ("oversized", "RESPONSE_TOO_LARGE"), ("malformed", "INVALID_RESPONSE"),
    ("too_many", "INVALID_RESPONSE"), ("timeout", "TIMEOUT"), ("offline", "UNAVAILABLE")])
def test_lookup_failure_is_safe_and_never_discards_model_fields(monkeypatch, failure, expected):
    body = b"{" if failure == "malformed" else b"x" * (module.MAX_BYTES + 1) if failure == "oversized" else None
    if failure == "too_many":
        body = json.dumps({"message": {"items": [record()] * 6}}).encode()
    session = transport(monkeypatch, status=failure if type(failure) is int else 200, body=body)
    if failure in {"timeout", "offline"}:
        session.get.side_effect = (requests.Timeout if failure == "timeout" else requests.ConnectionError)("private-body-key")
    result = preview()
    before = copy.deepcopy(result["metadata"])
    module.enrich_metadata(result, SimpleNamespace(metadata_lookup_timeout_seconds=3))
    audit = result["bibliographic_enrichment"]
    assert audit["status"] == "failed" and audit["error_code"] == expected
    assert result["metadata"] == before and "private-body-key" not in str(result)
    assert session.get.call_count == 1


def test_single_author_and_generic_publication_date_are_supported(monkeypatch):
    result = preview(authors=[AUTHORS[0]])
    row = record(author=[{"given": "Alice", "family": "Smith"}], **{
        "published-print": None, "published": {"date-parts": [[2024]]}})
    assert enrich(monkeypatch, result, [row])["status"] == "completed"
    assert result["metadata"]["year"] == 2024


@pytest.mark.parametrize("version", [
    None, {"kind": "unknown", "dois": []},
    {"kind": "manuscript", "dois": ["10.1234/library.1"]},
    {"kind": "publication", "dois": ["10.1234/different-version"]},
])
def test_same_work_is_insufficient_to_date_an_unconfirmed_pdf_version(monkeypatch, version):
    result = preview()
    result["document_version"] = version or {}
    audit = enrich(monkeypatch, result, [record()])
    assert result["metadata"]["year"] is None
    assert audit["year_decision"] == "version_not_confirmed"
    assert audit["filled_fields"] == ["source_url"]
    assert audit["candidates"][0]["selected_date"]["year"] == 2024


def test_registry_dates_for_different_years_require_selection_for_this_version(monkeypatch):
    result = preview()
    audit = enrich(monkeypatch, result, [record(**{"published-online": {"date-parts": [[2023]]}})])
    assert result["metadata"]["year"] is None
    assert audit["year_decision"] == "registry_dates_differ"


def test_preprint_revision_is_preserved_without_reporting_a_false_publication_conflict(monkeypatch):
    result = preview(year=2023, source_url="https://arxiv.org/abs/2111.13824v4")
    result["document_version"] = {"kind": "manuscript", "dois": []}
    audit = enrich(monkeypatch, result, [record()])
    assert result["metadata"]["year"] == 2023 and not audit["conflicts"]
