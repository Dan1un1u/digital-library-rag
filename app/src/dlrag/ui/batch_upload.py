"""Review several PDFs in the existing management navigation."""
import hashlib
import json
from urllib.parse import quote

import streamlit as st

from dlrag.shared.batch_limits import MAX_BATCH_FILES, MAX_BATCH_MIB
from dlrag.shared.i18n import error_message, labels, system_message, t
from dlrag.ui.library import DOMAINS, editable_topics, preview_discipline


def render_batch_upload(submit_job, base, max_upload_mb):
    st.subheader(t("批量入库"))
    st.caption(t("选择 PDF，核对每篇元数据，再一次发布。每批最多 {p0} 份，合计 {p1} MiB。",
                 p0=MAX_BATCH_FILES, p1=MAX_BATCH_MIB))
    files = st.file_uploader(t("选择多份 PDF"), type=["pdf"], accept_multiple_files=True,
                             max_upload_size=max_upload_mb, key="batch_files")
    assist = st.toggle(t("增强识别（推荐）"), value=True, key="batch_assist")
    lookup = st.toggle(t("联网补全出版资料"), disabled=not assist, key="batch_lookup")
    if not files:
        st.session_state.pop("batch_review", None)
        return
    raw = [file.getvalue() for file in files]
    if len(files) > MAX_BATCH_FILES or sum(map(len, raw)) > MAX_BATCH_MIB * 1024 * 1024:
        st.warning(t("已超出本批文件数量或大小限制。"))
        return
    signature = tuple((file.name, hashlib.sha256(value).hexdigest()) for file, value in zip(files, raw))
    review = st.session_state.get("batch_review")
    if not review or review["signature"] != signature:
        review = dict(signature=signature, previews=None, generation=0, result=None)
        st.session_state["batch_review"] = review
    if st.button(t("识别本批文献")):
        review["previews"] = [submit_job("/documents/metadata/jobs",
            files={"file": (file.name, value, "application/pdf")},
            data={"use_api": str(assist).lower(), "use_lookup": str(assist and lookup).lower()})
            for file, value in zip(files, raw)]
        review["generation"] += 1
        review["result"] = None
    if review["previews"] is None:
        return
    with st.form("batch_review_form"):
        reviewed = []
        for index, (file, preview) in enumerate(zip(files, review["previews"])):
            fields = (preview or {}).get("metadata", {})
            prefix = f"batch_{review['generation']}_{index}_{signature[index][1]}"
            with st.expander(file.name, expanded=True):
                selected = st.checkbox(t("本次入库"), value=True, key=prefix + "_include")
                for warning in (preview or {}).get("warnings", []):
                    st.caption(system_message(warning))
                title = st.text_input(t("标题"), value=fields.get("title") or "", key=prefix + "_title")
                authors = st.text_area(t("作者（每行一位）"), value="\n".join(fields.get("authors", [])),
                                       key=prefix + "_authors")
                year = st.text_input(t("版本年份（可留空）"), value=str(fields.get("year") or ""),
                                     key=prefix + "_year")
                domain = preview_discipline(preview)
                subject = st.selectbox(t("所属学科"), DOMAINS, index=DOMAINS.index(domain) if domain in DOMAINS else None,
                                       format_func=labels(DOMAINS), key=prefix + "_domain")
                topics = st.text_input(t("主题（逗号分隔）"), value=editable_topics(fields), key=prefix + "_topics")
                reviewed.append((selected, title, authors, year, subject, topics, fields))
        submitted = st.form_submit_button(t("发布本批文献"))
    if submitted:
        _submit_reviewed_batch(submit_job, files, raw, reviewed, review)
    if review["result"]:
        result = review["result"]
        if result["index_error"]:
            st.error(error_message(result["index_error"]))
        for name, item in zip(review["names"], result["items"]):
            with st.container(border=True):
                st.write(name)
                if item["status"] == "ready":
                    st.success(t("可阅读"))
                    st.link_button(t("阅读原文"), base.rstrip("/") + f"/documents/{quote(item['doc_id'], safe='')}/file")
                elif item["error"]:
                    st.error(error_message(item["error"]))


def _submit_reviewed_batch(submit_job, files, raw, reviewed, review):
    names, metadata, uploads = [], [], []
    for file, content, (selected, title, authors, year, domain, topics, fields) in zip(files, raw, reviewed):
        if not selected:
            continue
        try:
            year_value = int(year.strip()) if year.strip() else None
        except ValueError:
            st.error(t("{p0} 的版本年份须为整数。", p0=file.name))
            return
        if not domain:
            st.error(t("请为 {p0} 选择所属学科。", p0=file.name))
            return
        tags = [tag.strip() for tag in topics.replace("，", ",").split(",")]
        metadata.append({"title": title.strip() or None,
                         "authors": [author.strip() for author in authors.splitlines() if author.strip()],
                         "year": year_value, "topics": [domain, *[tag for tag in tags if tag and tag not in DOMAINS]],
                         "language": fields.get("language") or "unknown", "source_url": fields.get("source_url")})
        names.append(file.name)
        uploads.append(("files", (file.name, content, "application/pdf")))
    if not uploads:
        st.error(t("请至少选择一份文献。"))
        return
    review["names"] = names
    review["result"] = submit_job("/documents/batch/jobs", files=uploads,
                                  data={"metadata_json": json.dumps(metadata, ensure_ascii=False)})
