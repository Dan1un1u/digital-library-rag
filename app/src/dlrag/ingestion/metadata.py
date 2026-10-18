"""Local, conservative PDF metadata suggestions. No network, OCR or model calls.

Suggestions never update a library record; callers must present them for review.
PDF creation/modification dates are deliberately not publication years.
"""
import re
import statistics
import unicodedata

import fitz

from .errors import ProjectError


def clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\x00", "")).strip()


def useful_title(value):
    text = clean(value)
    return (5 <= len(text) <= 500 and not re.search(
        r"^(?:untitled|unknown|document\d*|microsoft (?:word|powerpoint)|latex|arxiv:|https?://)", text, re.I))


def author_names(value):
    value = clean(value)
    if not value or len(value) > 1000:
        return []
    if re.match(r"^\d+\s+", value):
        return []  # A leading affiliation number is not an author suffix.
    value = re.sub(r"^(?:authors?|作者)\s*[:：]\s*", "", value, flags=re.I)
    value = re.sub(r"[\d*∗⋆†‡⁎♦♣♥♠△]+", "", value).strip(" ,;，；")
    if re.search(r"@|https?://|universit|department|institute|laborator|\blabs?\b|\bresearch\b|\bcollege\b|\bschool\b|\bgoogle\b|\bopenai\b|\bdeepmind\b|copyright|abstract|摘要|大学|学院|研究所|实验室", value, re.I):
        return []
    parts = re.split(r"\s*[;；，、]\s*|\s+and\s+|\s*&\s*", value)
    if len(parts) == 1 and "," in value:
        comma = [x.strip() for x in value.split(",") if x.strip()]
        # Keep 'Last, First' intact; split only multiple complete names.
        if all(len(x.split()) >= 2 or re.fullmatch(r"[\u4e00-\u9fff]{2,4}", x) for x in comma):
            parts = comma
    if len(parts) == 1 and re.fullmatch(r"[\u4e00-\u9fff]{2,4}(?:\s+[\u4e00-\u9fff]{2,4})+", value):
        parts = value.split()
    result = []
    for part in parts:
        part = part.strip(" ,;，；")
        if not part or len(part) > 100:
            return []
        if re.fullmatch(r"[\u4e00-\u9fff]{2,5}", part):
            result.append(part)
        elif (2 <= len(part.split()) <= 6 and all(
                ch.isalpha() or ch.isspace() or unicodedata.category(ch).startswith("M") or ch in ".'’-,˘´ˆ¨`"
                for ch in part) and all(word[0].isupper() or word in {"de", "van", "von", "da", "del"}
                                       for word in part.split())):
            result.append(part)
        else:
            return []
    return list(dict.fromkeys(result))[:30]


def extract_metadata(file_path, filename=None):
    try:
        pdf = fitz.open(file_path)
    except Exception:
        raise ProjectError("INVALID_PDF", "无法读取 PDF 元数据") from None
    with pdf:
        if not pdf.is_pdf or pdf.needs_pass or not len(pdf):
            raise ProjectError("INVALID_PDF", "只支持非空、未加密的 PDF")
        suggested = dict(title=None, authors=[], year=None, language="unknown", source_url=None)
        sources, warnings = {}, ["自动识别结果仅供预填，请核对后再导入；未识别的字段留空。"]

        def put(field, value, method, excerpt, page=None):
            suggested[field] = value
            sources[field] = dict(method=method, pdf_page=page, excerpt=clean(excerpt)[:500])

        embedded = pdf.metadata or {}
        if useful_title(embedded.get("title")):
            put("title", clean(embedded["title"]), "pdf_metadata", embedded["title"])
        if embedded.get("author"):
            names = author_names(embedded["author"])
            if names:
                put("authors", names, "pdf_metadata", embedded["author"])

        try:
            page_texts = [pdf[i].get_text("text", sort=True) for i in range(min(2, len(pdf)))]
            first_text = page_texts[0][:15000]
            text = "\n".join(page_texts)[:30000]
            first = pdf[0]
            lines = []
            for block in first.get_text("dict", flags=0)["blocks"]:
                for line in block.get("lines", []):
                    spans = [s for s in line.get("spans", []) if clean(s.get("text"))]
                    if spans:
                        lines.append(dict(text=clean(" ".join(s["text"] for s in spans)),
                            size=max(s["size"] for s in spans), x0=line["bbox"][0], y0=line["bbox"][1], y1=line["bbox"][3]))
        except Exception:
            raise ProjectError("INVALID_PDF", "无法读取 PDF 首页文字") from None
        lines.sort(key=lambda x: (round(x["y0"] / 3), x["x0"]))
        title_bottom = None
        candidates = [line for line in lines if .04 * first.rect.height <= line["y0"] < .5 * first.rect.height
                      and useful_title(line["text"]) and not re.search(r"@|copyright|proceedings|www\.", line["text"], re.I)]
        if candidates:
            size = max(line["size"] for line in candidates)
            body_size = statistics.median(line["size"] for line in lines)
            if size >= body_size * 1.1:
                group = []
                for line in candidates:
                    if abs(line["size"] - size) > .6:
                        continue
                    if group and line["y0"] - group[-1]["y1"] > size * 1.6:
                        break
                    group.append(line)
                if group:
                    title_bottom = group[-1]["y1"]
                    title = " ".join(line["text"] for line in group)
                    if not suggested["title"] and useful_title(title):
                        put("title", title, "first_page_layout", title, 1)
            # Embedded title may use the same font size as body text.
            if title_bottom is None and suggested["title"]:
                for line in candidates:
                    if line["text"].casefold() in suggested["title"].casefold():
                        title_bottom = line["y1"]

        if not suggested["authors"]:
            names_found, author_lines, author_size = [], [], None
            for line in lines:
                explicit = bool(re.match(r"^(?:authors?|作者)\s*[:：]", line["text"], re.I))
                below_title = title_bottom is not None and title_bottom <= line["y0"] <= title_bottom + 160
                if not (explicit or below_title):
                    continue
                if re.match(r"arxiv\s*:", line["text"], re.I):
                    continue
                if "@" in line["text"]:
                    continue  # Emails can sit alongside each author's row.
                if re.match(r"^(?:abstract|摘要|introduction|引言)\b", line["text"], re.I):
                    break
                names = author_names(line["text"])
                if names:
                    if author_size is not None and line["size"] < author_size - .8:
                        break
                    author_size = line["size"] if author_size is None else author_size
                    names_found.extend(names)
                    author_lines.append(line["text"])
                elif names_found:
                    break
            if names_found:
                put("authors", list(dict.fromkeys(names_found))[:30], "first_page_text", "\n".join(author_lines), 1)
        if suggested["authors"]:
            warnings.append("作者候选可能因多行、分栏或 PDF 元数据不完整而遗漏，请核对完整名单和顺序。")

        # Only explicitly labelled publication/copyright dates, never PDF creation dates.
        date_patterns = [r"(?:published(?:\s+(?:online|on|in))?|publication date|出版(?:日期|年份)?|发表(?:日期|年份)?)\s*[:：]?\s*[^\n]{0,35}?\b((?:19|20)\d{2})\b",
                         r"(?:©|copyright)\s*(?:\(c\))?\s*((?:19|20)\d{2})\b"]
        for pattern in date_patterns:
            matches = list(re.finditer(pattern, first_text, re.I))
            years = {int(m.group(1)) for m in matches}
            if len(years) == 1:
                put("year", next(iter(years)), "document_date_candidate", matches[0].group(), 1)
                warnings.append("年份为正文日期候选，请确认是否为正式出版年份。")
                break
            if len(years) > 1:
                warnings.append("检测到多个不同年份，未自动选择出版年。")
                break

        arxiv = re.search(r"arxiv\s*:\s*(\d{4}\.\d{4,5})(?:v\d+)?", first_text, re.I)
        doi = re.search(r"(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)(10\.\d{4,9}/[^\s<>]+)", first_text, re.I)
        if arxiv:
            put("source_url", "https://arxiv.org/abs/" + arxiv.group(1), "document_identifier", arxiv.group())
        elif doi:
            put("source_url", "https://doi.org/" + doi.group(1).rstrip(".,;)]}"), "document_identifier", doi.group())
        if text.strip():
            letters = len(re.findall(r"[A-Za-z]", text))
            chinese = len(re.findall(r"[\u4e00-\u9fff]", text))
            if chinese >= 20 or letters >= 50:
                language = "mixed" if chinese >= 20 and letters >= 50 and chinese / (chinese + letters) > .15 else "zh" if chinese > letters else "en"
                put("language", language, "text_language_heuristic", "前两页文字的中英文字符分布")
        else:
            warnings.append("没有可提取文字，未启用 OCR；仅能使用 PDF 自带元数据或手动填写。")
        if not suggested["title"]:
            warnings.append("未可靠识别标题，请手动填写；留空将使用文件名并标注待核验。")
        if not suggested["authors"]:
            warnings.append("未可靠识别作者，请手动填写。")
        return dict(metadata=suggested, field_sources=sources, warnings=warnings,
                    requires_confirmation=True, page_count=len(pdf), method="local_pdf_metadata_and_text")
