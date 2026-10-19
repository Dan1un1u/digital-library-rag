"""Merge a keyword or evidence-backed LLM discipline into a metadata preview."""
import re
import unicodedata

from dlrag.shared.disciplines import DOMAINS, rule_discipline


def normalized(text):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip().casefold()


def supported_excerpt(excerpt, page_text):
    if normalized(excerpt) in normalized(page_text):
        return True
    # PDF line endings can split a word ("devel-\noped"); preserve all other
    # punctuation and word order instead of applying fuzzy semantic matching.
    unwrapped = re.sub(r"(?<=\w)[-\u00ad][ \t]*\r?\n[ \t]*(?=\w)", "", page_text)
    return normalized(excerpt) in normalized(unwrapped)


def complete_discipline(result, candidate=None, pages=()):
    metadata = result["metadata"]
    topics = metadata.setdefault("topics", [])
    value = rule_discipline(metadata)
    if value:
        method = "explicit" if value in topics else "keyword"
        if value not in topics:
            topics.append(value)
        result["discipline_classification"] = {"status": "classified", "method": method, "value": value}
        return 0
    result["discipline_classification"] = {"status": "pending", "method": "unresolved", "value": None}
    # Conflicting explicit selections need a user correction, never a model override.
    if any(domain in topics for domain in DOMAINS) or not isinstance(candidate, dict):
        return 0
    value, page = candidate.get("value"), candidate.get("pdf_page")
    excerpt, reason = candidate.get("excerpt"), candidate.get("reason", "")
    if (value not in DOMAINS or type(page) is not int or not 1 <= page <= len(pages)
            or not isinstance(excerpt, str) or not 1 <= len(excerpt.strip()) <= 1000
            or not isinstance(reason, str) or len(reason) > 500):
        return 0
    page_text = pages[page - 1].get("validation_text", pages[page - 1].get("text", ""))
    if not supported_excerpt(excerpt, page_text):
        return 0
    topics.append(value)
    result["discipline_classification"] = {"status": "classified", "method": "llm_page_classification",
        "value": value, "pdf_page": page, "excerpt": excerpt.strip(), "reason": reason.strip()}
    return 1
