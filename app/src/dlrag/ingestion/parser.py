"""Conservative, per-page PyMuPDF extraction. No OCR or inferred metadata."""
import re
from collections import Counter
from .errors import ProjectError

PARSER_VERSION = 'pymupdf-conservative-v4'


def _margin_key(line):
    return re.sub(r'\d+', '#', re.sub(r'\s+', ' ', line.strip()))


def normalize(text):
    text = text.replace('\x00', '')
    paragraphs = []
    for paragraph in re.split(r'\n\s*\n', text.replace('\r', '\n')):
        lines = [re.sub(r'[\t \u00a0]+', ' ', x).strip() for x in paragraph.splitlines()]
        lines = [x for x in lines if x]
        # Keep punctuation and hyphens intact; flatten visual wraps only.
        if lines:
            paragraphs.append(' '.join(lines))
    return '\n\n'.join(paragraphs)


def parse_pdf(file_path):
    from .fulltext import REVIEW_DIAGNOSTIC, scan_evidence
    from .text_quality import DIAGNOSTIC, encoding_evidence
    try:
        import fitz
    except ImportError as exc:
        raise ProjectError('DEPENDENCY_NOT_CONFIGURED', 'Install PyMuPDF') from exc
    try:
        pdf = fitz.open(file_path)
    except Exception as exc:
        raise ProjectError('INVALID_PDF', 'Unable to open PDF') from exc
    with pdf:
        if not pdf.is_pdf or pdf.needs_pass or len(pdf) == 0:
            raise ProjectError('INVALID_PDF', 'Expected an unencrypted, nonempty PDF')
        extracted = []
        margins = Counter()
        try:
            for page in pdf:
                # Coordinate sorting can replace CID control codes with spaces.
                # Inspect the native extraction before that evidence is lost.
                raw = page.get_text('text')
                blocks = page.get_text('blocks', sort=True)
                lines = raw.splitlines()
                # Only margin text located near the physical page edge qualifies.
                keys = set()
                for block in blocks:
                    if len(block) > 6 and block[6] != 0:
                        continue
                    if block[3] < page.rect.height * .09 or block[1] > page.rect.height * .91:
                        keys.update(_margin_key(x) for x in block[4].splitlines() if x.strip())
                margins.update(keys)
                left = [b for b in blocks if b[4].strip() and b[2] < page.rect.width * .56]
                right = [b for b in blocks if b[4].strip() and b[0] > page.rect.width * .44]
                diagnostics = []
                if '\x00' in raw or any('\x00' in b[4] for b in blocks):
                    diagnostics.append('NULL_CHARACTERS_REMOVED')
                if any(max(a[1], b[1]) < min(a[3], b[3]) for a in left for b in right):
                    diagnostics.append('MULTI_COLUMN_REVIEW_REQUIRED')
                if not raw.strip():
                    diagnostics.append('SCANNED_PAGE_NO_OCR' if page.get_images() else 'EMPTY_PAGE')
                extracted.append((raw, blocks, keys, diagnostics, page.rect.height))
        except Exception as exc:
            raise ProjectError('INVALID_PDF', 'PDF text extraction failed') from exc
        repeated = {key for key, count in margins.items()
                    if len(extracted) >= 2 and count >= max(2, (len(extracted)+1)//2)}
        result = []
        for number, (raw, blocks, keys, diagnostics, height) in enumerate(extracted, 1):
            removed = keys & repeated
            paragraphs = []
            for block in blocks:
                if len(block) > 6 and block[6] != 0:
                    continue
                margin = block[3] < height*.09 or block[1] > height*.91
                paragraphs.append('\n'.join(x for x in block[4].splitlines()
                                  if not margin or _margin_key(x) not in removed))
            cleaned = '\n\n'.join(paragraphs)
            if removed:
                diagnostics.append('REPEATED_MARGIN_REMOVED')
            normalized = normalize(cleaned)
            if scan_evidence(pdf[number-1], normalized) is not None:
                diagnostics.append(REVIEW_DIAGNOSTIC)
            if encoding_evidence(raw) is not None:
                diagnostics.append(DIAGNOSTIC)
            result.append({'pdf_page':number, 'printed_page':None, 'raw_text':raw,
                           'normalized_text':normalized, 'diagnostics':diagnostics})
        if not any(p['normalized_text'].strip() for p in result):
            reasons = sorted({d for p in result for d in p['diagnostics']})
            raise ProjectError('NO_EXTRACTABLE_TEXT', 'No usable text; ' + ', '.join(reasons))
        return result
