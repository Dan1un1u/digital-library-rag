"""Bounded, read-only PDF first-page thumbnails."""
from functools import lru_cache

import fitz


@lru_cache(maxsize=48)
def pdf_cover(path, modified_ns, size):
    # Stat values invalidate cached thumbnails when a file is replaced.
    with fitz.open(path) as document:
        page = document[0]
        scale = min(1, 640 / max(page.rect.width, page.rect.height))
        return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
