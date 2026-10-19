"""Language-neutral gate for structurally corrupt extracted text, not OCR repair."""
from .errors import ProjectError
from .fulltext import FulltextReviewRequired, _page_ranges

POLICY = "text-layer-encoding-v1"
DIAGNOSTIC = "TEXT_LAYER_ENCODING_REVIEW_REQUIRED"
MIN_SUSPECT_CHARACTERS = 8
MIN_SUSPECT_RATIO = .02


def encoding_evidence(text):
    """Ignore ordinary whitespace; do not score words, scripts or mathematics."""
    count = sum((ord(c) < 32 and c not in "\t\n\r") or 127 <= ord(c) < 160 or c == "\ufffd" for c in text)
    ratio = count / max(1, len(text))
    if count < MIN_SUSPECT_CHARACTERS or ratio < MIN_SUSPECT_RATIO:
        return None
    return {"characters": len(text), "suspect_characters": count, "suspect_ratio": round(ratio, 4)}


class TextLayerReviewRequired(FulltextReviewRequired):
    def __init__(self, pages, page_count):
        self.review = {"policy": POLICY, "page_count": page_count, "suspect_pages": sorted(set(pages)),
                       "requires_review": True, "reason": "text_encoding"}
        display = _page_ranges(self.review["suspect_pages"][:100]) + ("等" if len(pages) > 100 else "")
        ProjectError.__init__(self, "TEXT_LAYER_REVIEW_REQUIRED",
            f"PDF 第 {display} 页的文字层疑似编码异常，已暂停导入，未加入检索。"
            "请对照原页核对正文，完成 OCR 或更换可正确提取文字的版本后重新上传。"
            "增强元数据识别不能修复正文文字层。")


def require_readable_text(pages):
    suspect = [p["pdf_page"] for p in pages if DIAGNOSTIC in p.get("diagnostics", [])
               or encoding_evidence(p.get("raw_text", "")) is not None
               or encoding_evidence(p.get("normalized_text", "")) is not None]
    if suspect:
        raise TextLayerReviewRequired(suspect, len(pages))
