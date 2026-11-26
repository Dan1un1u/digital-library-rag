"""Deterministic flags for checking accessioned metadata against its version."""
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator

from dlrag.shared.disciplines import DOMAINS
from dlrag.shared.models import Input, Text, Year

from .metadata_year import body_text, date_evidence, normalize_evidence, preferred_dates


class MetadataCorrection(Input):
    authors: list[Text]
    year: Year | None
    discipline: Text
    expected_updated_at: Text
    evidence_page: Annotated[int, Field(strict=True, ge=1)] | None = None
    note: Annotated[str, StringConstraints(max_length=1000)] = ""

    @field_validator("discipline")
    @classmethod
    def valid_discipline(cls, value):
        if value not in DOMAINS:
            raise ValueError("请选择一项馆藏学科。")
        return value


def review_issues(document, first_page):
    checks = []
    authors = [normalize_evidence(author) for author in document["authors"]]
    title = normalize_evidence(document["title"])
    domains = [tag for tag in document["topics"] if tag in DOMAINS]
    if not authors:
        checks.append({"code": "AUTHORS_MISSING", "pdf_page": 1})
    if len(set(authors)) < len(authors):
        checks.append({"code": "AUTHORS_DUPLICATE", "pdf_page": 1})
    if any(len(author) >= 12 and author in title for author in authors):
        checks.append({"code": "AUTHOR_MATCHES_TITLE", "pdf_page": 1})
    if len(domains) != 1:
        checks.append({"code": "DISCIPLINE_CHECK", "pdf_page": 1})
    if first_page:
        evidence = date_evidence(body_text({"text": first_page["normalized_text"][:2500]}))
        dates = [row for row in preferred_dates(evidence)
                 if row[1] in {"revision", "version", "preprint", "issue", "publication"}]
        years = {row[0] for row in dates}
        if years and (len(years) > 1 or document["year"] not in years):
            checks.append({"code": "VERSION_YEAR_CHECK", "pdf_page": 1, "excerpt": dates[0][2][:300]})
    return checks
