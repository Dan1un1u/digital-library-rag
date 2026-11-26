"""Select, verify, and correct an existing catalogue record in place."""
from urllib.parse import quote

import streamlit as st

from dlrag.shared.disciplines import DOMAINS
from dlrag.shared.i18n import labels, t

REASONS = {
    "AUTHORS_MISSING": "作者字段为空",
    "AUTHORS_DUPLICATE": "作者名单含重复项",
    "AUTHOR_MATCHES_TITLE": "作者字段与题名文字重合",
    "DISCIPLINE_CHECK": "请确认所属学科",
    "VERSION_YEAR_CHECK": "请核对 PDF 版本年份",
}


def render_metadata_review(api, base):
    with st.expander(t("质量复核与纠错")):
        if st.session_state.get("review_saved"):
            st.success(t(st.session_state.pop("review_saved")))
        result = api("GET", "/documents/metadata/review")
        if not result:
            return
        pending_only = st.checkbox(t("仅显示建议复核的文献"), value=True, key="review_pending")
        candidates = {row["document"]["doc_id"]: row for row in result["records"]
                      if row["issues"] or not pending_only}
        st.caption(t('当前显示 {p0} 篇文献', p0=len(candidates)))
        if st.session_state.get("review_document") not in candidates:
            st.session_state.pop("review_document", None)
        doc_id = st.selectbox(t("选择已入库文献"), list(candidates), index=None,
                              format_func=lambda key: candidates[key]["document"]["title"], key="review_document")
        if not doc_id:
            return
        record = candidates[doc_id]
        document = record["document"]
        document_path = "/documents/" + quote(doc_id, safe="")
        original = base.rstrip("/") + document_path + "/file"
        st.link_button(t("阅读原文"), original)
        for issue in record["issues"]:
            st.write(t(REASONS[issue["code"]]))
            if issue.get("excerpt"):
                st.caption(issue["excerpt"])
            if issue.get("pdf_page"):
                st.link_button(t("打开该页"), original + f"#page={issue['pdf_page']}")
        revisions = api("GET", document_path + "/metadata/revisions")
        if revisions and revisions["revisions"]:
            st.markdown("**" + t("修订记录") + "**")
            _show_revisions(revisions["revisions"], original)
        _correction_form(api, document, document_path)


def _show_revisions(revisions, original):
    fields = {"authors": "作者", "year": "版本年份", "topics": "学科与主题"}
    for row in revisions:
        st.caption(row["reviewed_at"])
        st.table([{t("字段"): t(label), t("修改前"): _display(row["before"][key]),
                   t("修改后"): _display(row["after"][key])}
                  for key, label in fields.items() if row["before"][key] != row["after"][key]])
        if row["note"]:
            st.caption(row["note"])
        if row["evidence_page"]:
            st.link_button(t("证据页 {p0}", p0=row["evidence_page"]), original + f"#page={row['evidence_page']}")


def _display(value):
    if isinstance(value, list):
        return " · ".join(labels(value)(item) for item in value) or "—"
    return str(value) if value is not None else "—"


def _correction_form(api, document, document_path):
    key = "review_" + document["doc_id"] + document["updated_at"]
    domains = [domain for domain in DOMAINS if domain in document["topics"]]
    with st.form(key):
        authors = st.text_area(t("作者（每行一位）"), value="\n".join(document["authors"]))
        year = st.text_input(t("版本年份（可留空）"), value=str(document["year"] or ""))
        domain = st.selectbox(t("所属学科"), DOMAINS, index=DOMAINS.index(domains[0]) if len(domains) == 1 else None,
                              format_func=labels(DOMAINS))
        page = st.number_input(t("证据页（可选）"), min_value=1, max_value=document["page_count"], value=None, step=1)
        note = st.text_input(t("复核说明（可选）"), max_chars=1000)
        submitted = st.form_submit_button(t("保存修订"))
    if not submitted:
        return
    try:
        version_year = int(year.strip()) if year.strip() else None
    except ValueError:
        st.error(t("版本年份须为整数。"))
        return
    if not domain:
        st.error(t("请选择文献所属学科。"))
        return
    correction = {"authors": [line.strip() for line in authors.splitlines() if line.strip()],
                  "year": version_year, "discipline": domain, "evidence_page": page, "note": note,
                  "expected_updated_at": document["updated_at"]}
    with st.spinner(t("正在保存修订并更新检索…")):
        saved = api("PATCH", document_path + "/metadata", json=correction)
    if saved:
        st.session_state["review_saved"] = "已保存文献修订。" if saved["revision_id"] else "文献字段没有变化。"
        st.rerun()
