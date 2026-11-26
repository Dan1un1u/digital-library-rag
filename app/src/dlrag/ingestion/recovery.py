"""Eligibility, safe job errors and legacy page references for failed imports."""
import re

from .errors import ProjectError


RECOVERABLE_TEXT_ERRORS = ("FULLTEXT_REVIEW_REQUIRED", "TEXT_LAYER_REVIEW_REQUIRED", "NO_EXTRACTABLE_TEXT")
RECOVERY_MESSAGES = {
    "RECOVERY_NOT_AVAILABLE": "仅可为等待全文核对的原始文献提交修正版。",
    "REPLACEMENT_UNCHANGED": "上传的 PDF 与原件相同。请提交 OCR 后的 PDF 或修正版。",
    "REPLACEMENT_ALREADY_STORED": "这份 PDF 已作为其他文献收录或用于另一条恢复记录。请选择对应的修正版。",
    "RECOVERY_ALREADY_RESOLVED": "这条恢复记录已有可检索的修正版。",
    "RECOVERY_IN_PROGRESS": "已有一份修正版正在处理。若索引失败，请重新提交同一份 PDF。",
}


def validate_replacement(db, original_id, replacement_id, candidate_exists):
    """Called within the same write transaction that registers the candidate."""
    original = db.execute("""
        SELECT status, error_code FROM documents WHERE doc_id=?
        AND NOT EXISTS (SELECT 1 FROM document_replacements WHERE replacement_doc_id=?)
    """, (original_id, original_id)).fetchone()
    if not original or original["status"] != "failed" or original["error_code"] not in RECOVERABLE_TEXT_ERRORS:
        raise ProjectError("RECOVERY_NOT_AVAILABLE", RECOVERY_MESSAGES["RECOVERY_NOT_AVAILABLE"])
    if original_id == replacement_id:
        raise ProjectError("REPLACEMENT_UNCHANGED", RECOVERY_MESSAGES["REPLACEMENT_UNCHANGED"])
    if candidate_exists:
        link = db.execute("SELECT original_doc_id FROM document_replacements WHERE replacement_doc_id=?",
                          (replacement_id,)).fetchone()
        if link and link["original_doc_id"] == original_id:
            return
        raise ProjectError("REPLACEMENT_ALREADY_STORED", RECOVERY_MESSAGES["REPLACEMENT_ALREADY_STORED"])

    statuses = {row["status"] for row in db.execute("""
        SELECT d.status FROM document_replacements r
        JOIN documents d ON d.doc_id=r.replacement_doc_id WHERE r.original_doc_id=?
    """, (original_id,))}
    if "ready" in statuses:
        raise ProjectError("RECOVERY_ALREADY_RESOLVED", RECOVERY_MESSAGES["RECOVERY_ALREADY_RESOLVED"])
    if statuses - {"failed"}:
        raise ProjectError("RECOVERY_IN_PROGRESS", RECOVERY_MESSAGES["RECOVERY_IN_PROGRESS"])


def legacy_suspect_pages(document):
    """Recover page numbers already described in pre-migration gate messages."""
    if document["error_code"] not in ("FULLTEXT_REVIEW_REQUIRED", "TEXT_LAYER_REVIEW_REQUIRED"):
        return []
    found = re.match(r"PDF 第 ([0-9、–]+)等? 页", document["error_message"] or "")
    if not found:
        return []
    pages = []
    for value in found[1].split("、"):
        start, _, end = value.partition("–")
        if start.isdigit() and (not end or end.isdigit()):
            # Historic gate messages listed at most 100 pages before adding 等.
            first = int(start)
            pages.extend(range(first, min(int(end or start) + 1, first + 100 - len(pages))))
    return pages
