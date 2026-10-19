"""Conservative mixed-scan gate; detects missing text, does not perform OCR.

Large raster pages with little extractable text need review before indexing.
This is not a readability check and cannot certify OCR accuracy (ING-002).
"""
from .errors import ProjectError

POLICY = "mixed-scan-coverage-v1"
MIN_IMAGE_COVERAGE = .5
MAX_SPARSE_TEXT_CHARACTERS = 40
MIN_INK_RATIO = .003
REVIEW_DIAGNOSTIC = "SCAN_TEXT_LAYER_REVIEW_REQUIRED"


def _union_area(rectangles):
    """Union, so overlapping/duplicate logos cannot add up to a full scan."""
    xs = sorted({x for r in rectangles for x in (r.x0, r.x1)})
    area = 0.
    for left, right in zip(xs, xs[1:]):
        intervals = sorted((r.y0, r.y1) for r in rectangles if r.x0 < right and r.x1 > left)
        end, height = float("-inf"), 0.
        for lo, hi in intervals:
            height += max(0., hi - max(lo, end))
            end = max(end, hi)
        area += (right - left) * height
    return area


def scan_evidence(page, normalized_text):
    import fitz
    characters = len("".join(normalized_text.split()))
    if characters > MAX_SPARSE_TEXT_CHARACTERS:
        return None
    # Image boxes use unrotated page coordinates, including cropped pages.
    bounds = page.rect * page.derotation_matrix
    rectangles = []
    for image in page.get_image_info():
        rect = fitz.Rect(image["bbox"]) & bounds
        if not rect.is_empty and not rect.is_infinite:
            rectangles.append(rect)
    coverage = _union_area(rectangles) / bounds.get_area() if rectangles else 0.
    if coverage < MIN_IMAGE_COVERAGE:
        return None
    scale = 256 / max(page.rect.width, page.rect.height)
    samples = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csGRAY, alpha=False).samples
    # Do not block genuinely blank raster pages or uniform background fills.
    ink = sum(value < 240 for value in samples) / len(samples)
    if ink < MIN_INK_RATIO or max(samples) - min(samples) < 16:
        return None
    return {"image_coverage": round(coverage, 4), "text_characters": characters,
            "ink_ratio": round(ink, 4)}


def _page_ranges(pages):
    groups = []
    for page in pages:
        if groups and page == groups[-1][-1] + 1:
            groups[-1].append(page)
        else:
            groups.append([page])
    return "、".join(str(g[0]) if len(g) == 1 else f"{g[0]}–{g[-1]}" for g in groups)


class FulltextReviewRequired(ProjectError):
    def __init__(self, pages, page_count, text_pages):
        self.review = {"policy": POLICY, "page_count": page_count,
                       "pages_with_extractable_text": text_pages,
                       "suspect_pages": sorted(set(pages)), "requires_review": True}
        display = _page_ranges(self.review["suspect_pages"][:100])
        if len(pages) > 100:
            display += "等"
        super().__init__("FULLTEXT_REVIEW_REQUIRED",
            f"PDF 第 {display} 页疑似扫描页且缺少可用文字层，已暂停导入，未加入检索。"
            "请核对这些页面；若包含正文，请完成 OCR 或更换文字版后重新上传。"
            "图版等非文字页也需核对，元数据增强识别不能代替全文 OCR。")

    def public_error(self):
        # Only internally produced counts/page numbers, never PDF text/paths.
        return {"code": self.code, "message": self.message, "fulltext_review": self.review}


def require_complete_text(pages):
    suspect = [p["pdf_page"] for p in pages if REVIEW_DIAGNOSTIC in p.get("diagnostics", [])]
    if suspect:
        raise FulltextReviewRequired(suspect, len(pages),
                                     sum(bool(p["normalized_text"].strip()) for p in pages))
    from .text_quality import require_readable_text
    require_readable_text(pages)
