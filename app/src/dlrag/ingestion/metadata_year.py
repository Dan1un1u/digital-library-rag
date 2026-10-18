"""Publication-year evidence checks for the LLM-enhanced metadata path.

This validates an enhanced candidate; it does not infer a publication year from
an arXiv identifier, version date or a filename, and performs no external lookup.
Image-only evidence remains model-reported and still requires human review.
"""
from datetime import datetime
import re
import unicodedata


PUBLICATION = re.compile(
    r"(?:\bpublished\b|\bpublication\s+(?:date|year)\b|\bdate\s+of\s+publication\b|"
    r"\bproceedings\b|\bconference\b|\b(?:ICLR|ICML|NeurIPS|NIPS|IJCAI|AAAI|CVPR|ICCV|ECCV|ASPLOS|ICS|PMLR)\b|"
    r"出版(?:日期|年份|年)|发表(?:日期|年份|年))[^\n]{0,160}?\b((?:18|19|20)\d{2})\b", re.I)
COPYRIGHT = re.compile(r"(?:©|\bcopyright\b)\s*(?:\(c\)\s*)?((?:18|19|20)\d{2})\b", re.I)
NONPUBLICATION = re.compile(r"\barxiv\b|\b(?:revised|revision|submitted|submission|accepted|updated|preprint)\b|"
                            r"修订|修改|投稿|接收", re.I)
REFERENCES = re.compile(r"(?im)^\s*(?:\d+(?:\.\d+)*\s+)?(?:references|bibliography|参考文献)\s*[:：]?\s*$")
REASONS = {
    "not_provided": "没有明确出版年份证据",
    "invalid_candidate": "年份类型、页码或范围不合法",
    "nonpublication_date": "候选日期属于预印本、修订、投稿或接收日期",
    "missing_publication_context": "日期摘录没有明确出版或发表语境",
    "conflicting_publication_years": "证据包含相互冲突的出版年份",
    "year_not_supported": "证据中的出版年与候选值不一致",
    "excerpt_not_on_page": "摘录无法与所指页面的正文证据对应",
    "missing_page_evidence": "所指页面没有可核对的文字或图像",
}


def normalize_evidence(text):
    text = unicodedata.normalize("NFKC", text)
    # Keep the copyright cue: removing © would let a fabricated "© 2023"
    # quotation match a page that contains only a bare revision year.
    return re.sub(r"[^\w©]+|_", "", text, flags=re.UNICODE).casefold()


def validate_year(row, pages):
    """Return a bounded, grounded source or a reason; model date_type is not proof."""
    if row is None:
        return None, "not_provided"
    if not isinstance(row, dict):
        return None, "invalid_candidate"
    value, number, excerpt = row.get("value"), row.get("pdf_page"), row.get("excerpt")
    if (type(value) is not int or not 1800 <= value <= datetime.now().year + 1
            or type(number) is not int or not 1 <= number <= len(pages)
            or not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > 1000):
        return None, "invalid_candidate"
    kind = row.get("date_type")
    if kind is not None and not isinstance(kind, str):
        return None, "invalid_candidate"
    if kind not in {None, "publication", "copyright"}:
        return None, "nonpublication_date"
    # Associate the year with its own publication phrase, rather than accepting
    # any year merely because the same excerpt contains the word "published".
    years = set()
    for match in PUBLICATION.finditer(excerpt):
        before = excerpt[max(0, match.start() - 20):match.start()]
        negated = re.search(r"\bnot(?:\s+yet)?\s*$|\b(?:preprint|draft)\s+(?:was\s+)?$", before, re.I)
        if not NONPUBLICATION.search(match.group()) and not negated:
            years.add(int(match.group(1)))
    inferred_kind = "publication"
    if not years:
        years = {int(m.group(1)) for m in COPYRIGHT.finditer(excerpt)}
        inferred_kind = "copyright"
    if not years:
        return None, "missing_publication_context"
    if len(years) > 1:
        return None, "conflicting_publication_years"
    if value not in years:
        return None, "year_not_supported"
    page = pages[number - 1]
    text = page.get("validation_text", page.get("text")) or ""
    if text.strip():
        # Do not accept a source quotation occurring only in the references.
        body = REFERENCES.split(text, maxsplit=1)[0]
        if normalize_evidence(excerpt) not in normalize_evidence(body):
            return None, "excerpt_not_on_page"
        grounding = "page_text"
    elif page.get("image"):
        grounding = "model_read_page_image"
    else:
        return None, "missing_page_evidence"
    return {"value": value, "pdf_page": number, "excerpt": excerpt.strip(),
            "date_type": inferred_kind, "grounding": grounding}, None


def merge_year_candidate(result, row, pages):
    """Validate the enhanced year and any retained seed year at the same boundary."""
    source, reason = validate_year(row, pages)
    metadata, sources = result["metadata"], result["field_sources"]
    review = {"policy": "publication-year-evidence-v1"}
    if source:
        metadata["year"] = source["value"]
        sources["year"] = {"method": "api_page_recognition", **{k: v for k, v in source.items() if k != "value"}}
        result["year_review"] = {**review, "status": "candidate_supported", "source": "api",
                                 "grounding": source["grounding"]}
        return 1
    # Rejecting an API value must not quietly leave an unverified seed year in
    # the enhanced output. Keep a seed only when its source passes this policy.
    previous = sources.get("year") or {}
    fallback, _ = validate_year({"value": metadata.get("year"), **previous}, pages)
    if fallback:
        metadata["year"] = fallback["value"]
        sources["year"] = {**previous, "date_type": fallback["date_type"], "grounding": fallback["grounding"]}
        result["year_review"] = {**review, "status": "candidate_supported", "source": "validated_seed",
                                 "rejected_api_reason": reason}
        if row is not None:
            result.setdefault("warnings", []).append("API 年份候选未采纳；保留已有、具有出版依据的年份，仍请核对。")
    else:
        if "year" in metadata:
            metadata["year"] = None
        sources.pop("year", None)
        result["year_review"] = {**review, "status": "needs_confirmation", "reason": reason,
                                 "rejected_value": row.get("value") if isinstance(row, dict) and type(row.get("value")) is int else None}
        result.setdefault("warnings", []).append(
            "出版年份待核对：" + REASONS[reason] + "；已留空，不使用修订日期代填。")
    return 0
