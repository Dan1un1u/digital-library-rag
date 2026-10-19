"""Ground a year in the supplied PDF version, rather than its later publication."""
from datetime import datetime
import re
import unicodedata


POLICY = "collected-version-year-v2"
YEAR = r"((?:18|19|20)\d{2})(?!\d)"
REFERENCES = re.compile(r"(?im)^\s*(?:\d+(?:\.\d+)*\s+)?(?:references|bibliography|参考文献)\s*[:：]?\s*$")
PATTERNS = [
    ("revision", r"\b(?:revised|revision|updated|last\s+modified)\b|修订|修改|更新"),
    ("submission", r"\b(?:submitted|received)\b(?!\s+to\b)|投稿日期|收稿日期"),
    ("acceptance", r"\baccepted\b|接收日期|录用日期"),
    ("preprint", r"\b(?:posted|preprint\s+(?:posted|published))\b|预印本公开"),
    ("publication", r"\bpublished\b|\bpublication\s+(?:date|year)\b|\bdate\s+of\s+publication\b|"
                    r"\bproceedings\b|\bconference\b|出版(?:日期|年份|年)|发表(?:日期|年份|年)"),
    ("copyright", r"©|\bcopyright\b"),
]
PATTERNS = [(kind, re.compile("(?:" + cue + r")[^\n.!?。]{0,160}?\b" + YEAR, re.I))
            for kind, cue in PATTERNS]
ARXIV_DATE = re.compile(r"\barxiv\s*(?::\s*\d{4}\.\d{4,5})?\s*v\d+\b"
                        r"(?:\s*\[[^\]\n]{1,30}\])?\s+\d{1,2}\s+[A-Za-z]{3,9}\s+" + YEAR, re.I)
NEGATIVE = re.compile(r"\b(?:not|never|no|unpublished)\b|\bunder\s+review\b|\bsubmitted\s+to\b|尚未|未发表|未出版", re.I)
REASONS = {
    "not_provided": "没有提供版本年份候选",
    "invalid_candidate": "年份类型、页码或范围不合法",
    "missing_version_context": "页面没有可对应到所收录版本的日期说明",
    "conflicting_version_years": "同类版本日期存在不同年份，需要核对",
    "year_not_supported": "候选年份与当前版本的日期依据不一致",
    "excerpt_not_on_page": "摘录无法与所指页面的正文证据对应",
    "missing_page_evidence": "所指页面没有可核对的文字或图像",
}


def normalize_evidence(text):
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"[^\w©]+|_", "", text, flags=re.UNICODE).casefold()


def body_text(page):
    return REFERENCES.split(page.get("validation_text", page.get("text")) or "", maxsplit=1)[0]


def date_evidence(text):
    """Read labelled dates in context; a target conference year is not a date."""
    evidence = []
    for match in ARXIV_DATE.finditer(text):
        evidence.append((int(match.group(1)), "version", match.group().strip()))
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            # Keep preceding words, even if the model excerpt dropped 'Not'.
            start = max(text.rfind("\n", 0, match.start()), text.rfind(". ", 0, match.start()),
                        text.rfind("。", 0, match.start())) + 1
            context = text[start:match.end()]
            if NEGATIVE.search(context):
                continue
            if kind in {"submission", "acceptance"} and re.search(
                    r"\b(?:ICLR|ICML|NeurIPS|conference|workshop)\b", match.group(), re.I):
                continue
            inferred = "preprint" if kind == "publication" and re.search(r"\b(?:preprint|arxiv)\b", context, re.I) else kind
            evidence.append((int(match.group(1)), inferred, context.strip()))
    return evidence


def preferred_dates(evidence):
    # A stamp or explicit revision belongs to this file. A coexisting publisher
    # date describes another stage and must not displace the current version.
    versions = [e for e in evidence if e[1] in {"version", "revision"}]
    if versions:
        latest = max(e[0] for e in versions)
        return [e for e in versions if e[0] == latest]
    preprints = [e for e in evidence if e[1] == "preprint"]
    if preprints:
        return [e for e in preprints if e[0] == max(e[0] for e in preprints)]
    publications = [e for e in evidence if e[1] == "publication"]
    if publications:
        return publications
    manuscript = [e for e in evidence if e[1] in {"submission", "acceptance"}]
    if manuscript:
        latest = max(e[0] for e in manuscript)
        return [e for e in manuscript if e[0] == latest]
    return [e for e in evidence if e[1] == "publication"] or evidence


def validate_year(row, pages):
    """The document context decides date_type; a model's label is not proof."""
    if row is None:
        return None, "not_provided"
    if not isinstance(row, dict):
        return None, "invalid_candidate"
    value, number, excerpt = row.get("value"), row.get("pdf_page"), row.get("excerpt")
    if (type(value) is not int or not 1800 <= value <= datetime.now().year + 1
            or type(number) is not int or not 1 <= number <= len(pages)
            or not isinstance(excerpt, str) or not excerpt.strip() or len(excerpt) > 1000
            or not isinstance(row.get("date_type", "version"), str)):
        return None, "invalid_candidate"
    page = pages[number - 1]
    text = body_text(page)
    if text.strip():
        if normalize_evidence(excerpt) not in normalize_evidence(text):
            return None, "excerpt_not_on_page"
        evidence = date_evidence(text)
        all_evidence = [e for p in pages for e in date_evidence(body_text(p))]
        grounding = "page_text"
    elif page.get("image"):
        evidence = all_evidence = date_evidence(excerpt)
        grounding = "model_read_page_image"
    else:
        return None, "missing_page_evidence"
    preferred = preferred_dates(all_evidence)
    if not preferred:
        return None, "missing_version_context"
    if len({e[0] for e in preferred}) > 1:
        return None, "conflicting_version_years"
    proof = normalize_evidence(excerpt)
    supported = [e for e in evidence if e in preferred and e[0] == value and
                 (proof in normalize_evidence(e[2]) or normalize_evidence(e[2]) in proof)]
    if not supported or not re.search(r"(?<!\d)" + str(value) + r"(?!\d)", excerpt):
        return None, "year_not_supported"
    _, kind, context = supported[0]
    return {"value": value, "pdf_page": number, "excerpt": excerpt.strip(),
            "date_type": kind, "context": context[:1000], "grounding": grounding}, None


def document_version(pages):
    """Only a publisher layout plus a printed DOI can bind an external date."""
    text = "\n".join(body_text(p) for p in pages)
    manuscript = re.search(r"\barxiv\b|\bpreprint\b|\bunder\s+review\b|\bsubmitted\s+to\b|"
                           r"\b(?:author|accepted)\s+manuscript\b|预印本|作者稿", text, re.I)
    dois = re.findall(r"(?:https?://(?:dx\.)?doi\.org/|\bdoi\s*:\s*)(10\.\d{4,9}/[^\s<>]+)", text, re.I)
    publisher = re.search(r"\b(?:proceedings|journal|IEEE|ACM|Springer|Elsevier|ISCA)\b|"
                          r"published\s+as\s+a\s+conference\s+paper|期刊|学报", text, re.I)
    return {"kind": "manuscript" if manuscript else "publication" if publisher and dois else "unknown",
            "dois": sorted({d.rstrip(".,;)]}").lower() for d in dois})}


def merge_year_candidate(result, row, pages):
    """Apply the same version policy to the model candidate and retained seed."""
    result["document_version"] = document_version(pages)
    source, reason = validate_year(row, pages)
    metadata, sources = result["metadata"], result["field_sources"]
    review = {"policy": POLICY}
    result["warnings"] = [w for w in result.get("warnings", []) if not w.startswith(
        ("年份为正文日期候选", "检测到多个不同年份", "版本年份待核对", "出版年份待核对"))]
    if source:
        metadata["year"] = source["value"]
        sources["year"] = {"method": "api_page_recognition", **{k: v for k, v in source.items() if k != "value"}}
        result["year_review"] = {**review, "status": "candidate_supported", "source": "api",
                                 "date_type": source["date_type"], "grounding": source["grounding"]}
        return 1
    previous = sources.get("year") or {}
    fallback, _ = validate_year({"value": metadata.get("year"), **previous}, pages)
    if fallback:
        metadata["year"] = fallback["value"]
        sources["year"] = {**previous, **{k: v for k, v in fallback.items() if k != "value"}}
        result["year_review"] = {**review, "status": "candidate_supported", "source": "validated_seed",
                                 "date_type": fallback["date_type"], "rejected_api_reason": reason}
    else:
        metadata["year"] = None
        sources.pop("year", None)
        result["year_review"] = {**review, "status": "needs_confirmation", "reason": reason,
                                 "rejected_value": row.get("value") if isinstance(row, dict) and type(row.get("value")) is int else None}
        result["warnings"].append("版本年份待核对：" + REASONS[reason] + "；已留空，可根据所收录文件核对后填写。")
    return 0
