"""Review blocked PDF pages and submit a corrected copy from document management."""
import json
from urllib.parse import quote

import streamlit as st

from dlrag.ingestion.recovery import RECOVERABLE_TEXT_ERRORS
from dlrag.shared.disciplines import DOMAINS
from dlrag.shared.i18n import error_message, labels, t
from dlrag.ui.library import document_status


def render_document_recovery(api, submit_job, base, max_upload_mb, documents):
    if not any(d["status"] == "failed" and d.get("error_code") in RECOVERABLE_TEXT_ERRORS for d in documents):
        return set()
    result = api("GET", "/document-recoveries")
    if not result or not result["cases"]:
        return set()
    cases = {case["original"]["doc_id"]: case for case in result["cases"]}
    recovered = {doc_id for doc_id, case in cases.items() if case["status"] == "recovered"}

    with st.expander(t("入库失败恢复"), key="recovery_panel", on_change="rerun"):
        if st.session_state.pop("recovery_saved", False):
            st.success(t("修正版已入库，可在馆藏中检索。"))
        doc_id = st.selectbox(t("选择待恢复文献或查看记录"), list(cases), index=None,
                              format_func=lambda key: _case_label(cases[key]), key="recovery_document")
        if doc_id is None:
            return recovered
        case = cases[doc_id]
        original = case["original"]
        path = "/documents/" + quote(doc_id, safe="")
        source = base.rstrip("/") + path + "/file"
        st.caption(t("已恢复") if doc_id in recovered else t("待恢复"))
        if doc_id not in recovered:
            _show_error(original)
        st.link_button(t("打开失败原件"), source)
        if case["suspect_pages"]:
            _show_problem_page(case["suspect_pages"], source, doc_id)
        else:
            st.caption(t("这条记录没有页码，请打开原件核对。"))

        if case["status"] == "pending":
            if any(attempt["document"]["status"] != "failed" for attempt in case["attempts"]):
                st.info(t("已有修正版等待处理。如需重试，请重新提交同一份 PDF。"))
            if _replacement_form(submit_job, original, path, max_upload_mb):
                # A failed candidate stays in the case alongside the original.
                latest = api("GET", "/document-recoveries")
                if latest:
                    case = next((item for item in latest["cases"] if item["original"]["doc_id"] == doc_id), case)
        _show_attempts(case["attempts"], base)
    return recovered


def _case_label(case):
    original = case["original"]
    return f"{original['title']} · {original['file_sha256'][:8]}"


def _show_error(document):
    code = document.get("error_code")
    if code:
        message = document["error_message"]
        if code == "NO_EXTRACTABLE_TEXT":
            message = t("PDF 没有可提取正文，请先进行 OCR 或准备可提取文字的 PDF。")
        st.warning(error_message({"code": code, "message": message}))


def _show_problem_page(pages, source, doc_id):
    page = st.selectbox(t("问题页（PDF 页码）"), pages, key="recovery_page_" + doc_id)
    st.link_button(t("打开该页"), source + f"#page={page}")


def _show_attempts(attempts, base):
    if not attempts:
        return
    st.markdown("**" + t("修正版记录") + "**")
    for attempt in reversed(attempts):
        doc = attempt["document"]
        submitted = attempt["submitted_at"][:16].replace("T", " ") + " UTC"
        st.caption(f"{submitted} · {document_status(doc)} · {doc['file_sha256'][:8]}")
        source = base.rstrip("/") + "/documents/" + quote(doc["doc_id"], safe="") + "/file"
        st.link_button(t("打开已提交的修正版"), source, key="recovery_attempt_" + doc["doc_id"])
        if attempt["suspect_pages"]:
            _show_problem_page(attempt["suspect_pages"], source, doc["doc_id"])
        _show_error(doc)


def _replacement_form(submit_job, original, path, max_upload_mb):
    st.caption(t("对原件完成 OCR，或准备同一文献的可读 PDF。提交前请核对修正版的题名、作者和版本年份。"))
    domains = [domain for domain in DOMAINS if domain in original["topics"]]
    with st.form("recovery_form_" + original["doc_id"]):
        corrected = st.file_uploader(t("修正版 PDF（单份最大 {p0} MB）", p0=max_upload_mb),
                                     type=["pdf"], max_upload_size=max_upload_mb,
                                     key="recovery_pdf_" + original["doc_id"])
        title = st.text_input(t("标题"), value=original["title"])
        authors = st.text_area(t("作者（每行一位）"), value="\n".join(original["authors"]))
        year = st.text_input(t("版本年份（可留空）"), value=str(original["year"] or ""))
        domain = st.selectbox(t("所属学科"), DOMAINS, index=DOMAINS.index(domains[0]) if len(domains) == 1 else None,
                              format_func=labels(DOMAINS))
        submitted = st.form_submit_button(t("提交修正版并重新验证"))
    if not submitted:
        return False
    if corrected is None:
        st.error(t("请先选择 PDF 文件。"))
        return False
    if not title.strip():
        st.error(t("请填写修正版标题。"))
        return False
    try:
        version_year = int(year.strip()) if year.strip() else None
    except ValueError:
        st.error(t("版本年份须为整数。"))
        return False
    if domain is None:
        st.error(t("请选择文献所属学科。"))
        return False
    metadata = {"title": title, "authors": [line.strip() for line in authors.splitlines() if line.strip()],
                "year": version_year, "topics": [domain, *(tag for tag in original["topics"] if tag not in DOMAINS)]}
    saved = submit_job(path + "/recovery/jobs", files={"file": (corrected.name, corrected.getvalue(), "application/pdf")},
                       data={"metadata_json": json.dumps(metadata)})
    if saved:
        st.session_state["recovery_saved"] = True
        st.rerun()
    return True
