"""Opt-in, reviewable Crossref enrichment after successful LLM recognition.

Only title and author names leave the application. A unique exact title and
strong author agreement are required; search rank alone is never evidence.
"""
from datetime import datetime, timezone
import json
import math
import re
import unicodedata
from urllib.parse import quote

import requests

ENDPOINT = "https://api.crossref.org/works"
POLICY = "crossref-collected-version-v2"
MAX_BYTES = 512 * 1024
FORMAL_TYPES = {"journal-article", "proceedings-article"}


class LookupFailure(Exception):
    def __init__(self, code):
        self.code = code


def normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value), flags=re.UNICODE).casefold()


def query_crossref(title, authors, timeout):
    # A fresh session has no model credentials, cookies or environment auth.
    with requests.Session() as session:
        session.trust_env = False
        session.headers["User-Agent"] = "DigitalLibraryMetadata/0.1 (reviewable bibliographic enrichment)"
        with session.get(ENDPOINT, params={
                "query.bibliographic": title + " " + " ".join(authors[:2]), "rows": 5,
                "select": "DOI,title,subtitle,author,type,published-print,published-online,published"},
                timeout=(min(3, timeout), timeout), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise LookupFailure("RATE_LIMIT" if response.status_code == 429 else "HTTP_ERROR")
            body = bytearray()
            for block in response.iter_content(16384):
                body.extend(block)
                if len(body) > MAX_BYTES:
                    raise LookupFailure("RESPONSE_TOO_LARGE")
            payload = json.loads(body)
    items = payload["message"]["items"]
    if not isinstance(items, list) or len(items) > 5:
        raise LookupFailure("INVALID_RESPONSE")
    return items


def publication_dates(record):
    """Keep the date kind; never infer a year from created/issued/accepted."""
    dates = []
    for kind in ("published-print", "published-online", "published"):
        part = record.get(kind, {})
        parts = part.get("date-parts") if isinstance(part, dict) else None
        if (not isinstance(parts, list) or len(parts) != 1 or not isinstance(parts[0], list)
                or not 1 <= len(parts[0]) <= 3):
            continue
        values = parts[0]
        if any(type(x) is not int for x in values) or not 1800 <= values[0] <= datetime.now().year + 1:
            continue
        try:
            datetime(*(values + [1] * (3 - len(values))))
        except ValueError:
            continue
        dates.append({"kind": kind, "date_parts": values, "year": values[0]})
    # Prefer specifically labelled online/print dates to the generic field.
    specific = [d for d in dates if d["kind"] != "published"]
    chosen = min(specific or dates, key=lambda d: d["date_parts"] + [1] * (3 - len(d["date_parts"]))) if dates else None
    return dates, chosen


def match_record(record, title, authors):
    if not isinstance(record, dict) or record.get("type") not in FORMAL_TYPES:
        return None
    titles, subtitles = record.get("title"), record.get("subtitle") or []
    if (not isinstance(titles, list) or not titles or not isinstance(titles[0], str)
            or not isinstance(subtitles, list) or any(not isinstance(s, str) for s in subtitles)):
        return None
    full_title = titles[0]
    for subtitle in subtitles:
        if normalized(subtitle) not in normalized(full_title):
            full_title += ": " + subtitle
    if normalized(full_title) != normalized(title):
        return None
    rows = record.get("author")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        return None
    names = []
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("given"), str)
                or not isinstance(row.get("family"), str)):
            return None
        names.append((row["given"] + " " + row["family"]).strip())
    local, remote = [normalized(n) for n in authors], [normalized(n) for n in names]
    overlap = len(set(local) & set(remote))
    required = max(1 if max(len(local), len(remote)) == 1 else 2,
                   math.ceil(.8 * max(len(set(local)), len(set(remote)))))
    if not remote[0] or local[0] != remote[0] or overlap < required:
        return None
    doi = record.get("DOI")
    if not isinstance(doi, str) or len(doi) > 200 or not re.fullmatch(r"10\.\d{4,9}/[-A-Za-z0-9._;()/:]+", doi):
        return None
    doi = doi.lower()
    dates, chosen = publication_dates(record)
    return {"title": full_title, "authors": names, "doi": doi,
            "source_url": "https://doi.org/" + quote(doi, safe="/:;()._-"),
            "record_url": ENDPOINT + "/" + quote(doi, safe=""), "type": record["type"],
            "dates": dates, "selected_date": chosen,
            "match": {"title": "normalized_exact", "first_author": "exact",
                      "author_overlap": overlap, "required_overlap": required}}


def enrich_metadata(result, settings):
    """Fill missing fields only; preserve existing values and expose conflicts."""
    metadata = result["metadata"]
    missing = [f for f in ("year", "source_url") if metadata.get(f) is None or metadata.get(f) == ""]
    audit = {"policy": POLICY, "provider": "crossref", "status": "not_needed",
             "missing_before": missing, "filled_fields": [], "conflicts": [], "candidates": []}
    result["bibliographic_enrichment"] = audit
    if not missing:
        return
    title, authors = metadata.get("title"), metadata.get("authors")
    if (not isinstance(title, str) or not 5 <= len(title) <= 500 or not isinstance(authors, list)
            or not 1 <= len(authors) <= 100
            or any(not isinstance(n, str) or not 1 < len(n.strip()) <= 100 for n in authors)):
        audit["status"] = "insufficient_identity"
        result["warnings"].append("书目补全需要可靠的题名与作者，请核对后重试或手工补充。")
        return
    audit["queried_at"] = datetime.now(timezone.utc).isoformat()
    try:
        records = query_crossref(title, authors, settings.metadata_lookup_timeout_seconds)
        matches = [m for r in records if (m := match_record(r, title, authors)) is not None]
        # Identical duplicate rows are harmless; conflicting records remain ambiguous.
        matches = list({json.dumps(m, sort_keys=True): m for m in matches}.values())
    except Exception as exc:
        audit["status"] = "failed"
        audit["error_code"] = (exc.code if isinstance(exc, LookupFailure) else
                               "TIMEOUT" if isinstance(exc, requests.Timeout) else
                               "UNAVAILABLE" if isinstance(exc, requests.RequestException) else "INVALID_RESPONSE")
        result["warnings"].append("外部书目查询未完成，已保留识别结果；可稍后重试或手工补充。")
        return
    audit["candidates"] = matches
    if len(matches) != 1:
        audit["status"] = "ambiguous" if matches else "no_match"
        result["warnings"].append("书目查询未找到唯一、题名和作者均吻合的出版记录；缺失字段保持为空，请核对。")
        return
    record = matches[0]
    chosen = record["selected_date"]
    version = result.get("document_version", {})
    same_version = version.get("kind") == "publication" and record["doi"] in version.get("dois", [])
    date_years = {d["year"] for d in record["dates"]}
    audit["year_decision"] = ("same_publication_version" if same_version and len(date_years) == 1 else
                              "registry_dates_differ" if same_version and len(date_years) > 1 else
                              "version_not_confirmed" if not same_version else "no_registry_date")
    values = {"source_url": record["source_url"], "year": chosen["year"] if chosen else None}
    for field, value in values.items():
        if value is None:
            continue
        if field not in missing:
            if metadata.get(field) != value and ((field == "year" and same_version) or
                                                (field != "year" and str(metadata.get(field)).startswith("https://doi.org/"))):
                audit["conflicts"].append({"field": field, "existing": metadata[field], "external": value})
            continue
        if field == "year" and audit["year_decision"] != "same_publication_version":
            continue
        metadata[field] = value
        result["field_sources"][field] = {"method": "bibliographic_lookup", "provider": "crossref",
            "record_url": record["record_url"], "retrieved_at": audit["queried_at"],
            "date_type": chosen["kind"] if field == "year" else None,
            "excerpt": (chosen["kind"] + ": " + "-".join(map(str, chosen["date_parts"]))) if field == "year" else record["doi"]}
        audit["filled_fields"].append(field)
        if field == "year":
            result["year_review"] = {"policy": POLICY, "status": "candidate_supported", "source": "crossref",
                                     "grounding": "registry_record", "date_type": chosen["kind"]}
            result["warnings"] = [w for w in result["warnings"] if not w.startswith(("版本年份待核对", "出版年份待核对"))]
    audit["status"] = "completed"
    if audit["filled_fields"]:
        result["warnings"].append("已依据题名和作者吻合的 Crossref 出版记录补全候选字段；DOI 可作为相关出版来源，年份还须与所收录版本对应，请核对后导入。")
    if audit["conflicts"]:
        result["warnings"].append("现有字段与外部书目存在差异，未自动覆盖，请核对后选择。")
    if "year" in missing and metadata.get("year") is None:
        result["warnings"].append("外部出版日期未能确定对应所收录版本；版本年份继续留空。相关记录仅供核对，可按文件上的日期手动填写。")
