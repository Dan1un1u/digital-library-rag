"""python -m streamlit run src/dlrag/ui/app.py"""
import json
import hashlib
import os
import time
from urllib.parse import quote

import streamlit as st
from dotenv import dotenv_values
from dlrag.ui.client import call_api, citation_numbers, clarified_question
from dlrag.ui.citations import claim_html, marked_text, source_url
from dlrag.ui.library import DOMAINS, STYLE, cover_card, discipline, domain_counts, document_status
from dlrag.ui.state import reset_question, reset_upload, reset_view

st.set_page_config(page_title="专题数字图书馆", page_icon="📚", layout="wide")
st.markdown(STYLE, unsafe_allow_html=True)
st.title("专题数字图书馆")
st.caption("查找文献 · 依据原文提问 · 核对每一条引用")
base = os.environ.get("API_BASE_URL") or dotenv_values(".env").get("API_BASE_URL") or "http://127.0.0.1:8000"


def api(method, path, **kwargs):
    value = call_api(base, method, path, **kwargs)
    if "_failure" in value:
        st.error(value["_failure"]["message"])
        st.caption("错误标识：" + value["_failure"]["code"])
        return None
    return value


DOCUMENT_STAGES = {
    "queued": (5, "等待处理"), "file_received": (12, "已接收 PDF"),
    "local_reading": (25, "读取文献信息"), "page_preparation": (35, "准备页面图像"),
    "api_recognition": (55, "API 正在识别标题、作者等信息"),
    "bibliographic_lookup": (95, "查询出版资料，补全缺失信息"),
    "metadata_validation": (90, "校验识别结果"), "waiting": (20, "等待馆藏处理"),
    "document_parsing": (40, "解析文献正文"), "document_processing": (65, "处理文献，准备搜索"),
    "document_saving": (95, "保存文献信息"), "done": (100, "处理完成"), "error": (0, "处理未完成")}


def document_with_progress(path, **kwargs):
    bar = st.progress(0, text="正在提交 PDF…")
    detail = st.empty()
    value = api("POST", path, **kwargs)
    if not value:
        bar.empty()
        return None
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        job = api("GET", "/document-jobs/" + value["job_id"])
        if not job:
            bar.empty()
            return None
        percent, label = DOCUMENT_STAGES.get(job["stage"], (10, "处理中"))
        bar.progress(percent, text=label)
        detail.caption(f"已用时 {job['elapsed_seconds']:.1f} 秒 · 按实际处理阶段显示进度")
        if job["stage"] == "error":
            st.error(job["error"]["message"])
            return None
        if job["stage"] == "done":
            if job["result"].get("api_assistance", {}).get("status") in {"failed", "unavailable"}:
                bar.progress(100, text="本机识别完成，增强识别未成功")
            return job["result"]
        time.sleep(0.35)
    st.warning("处理超过 5 分钟，后台可能仍在继续，请到文献管理查看结果后再重试。")
    return None


health = api("GET", "/health")
if not health:
    st.info("先在另一个终端启动后端：python -m dlrag.api.main")
    st.stop()
if health["status"] != "ready":
    st.info("部分服务暂不可用，可在“上传与管理 → 系统设置”查看详情。")

st.sidebar.markdown("### 📚 阅读与发现")
st.sidebar.caption("专题数字图书馆 · 您的文献工作台")
page = st.sidebar.radio("功能", ["馆藏展示", "搜索与问答", "上传与管理"],
                        key="navigation_page", on_change=reset_view, args=(st.session_state,))
section = None
if page == "馆藏展示":
    section = st.sidebar.radio("馆藏导航", ["馆藏文献分类", "热门电子文献资源"],
                               key="library_section", on_change=reset_view, args=(st.session_state,))
elif page == "上传与管理":
    section = st.sidebar.radio("管理导航", ["上传文献", "文献管理", "系统设置"],
                               key="management_section", on_change=reset_view, args=(st.session_state,))
start_year = end_year = topics_text = ""
if page in {"馆藏展示", "搜索与问答"}:
    with st.sidebar.expander("筛选文献", expanded=False):
        start_year = st.text_input("起始年份", placeholder="不限")
        end_year = st.text_input("结束年份", placeholder="不限")
        topics_text = st.text_input("主题（逗号分隔）", placeholder="信息检索,数字图书馆")
try:
    filters = {"year_from": int(start_year) if start_year.strip() else None,
               "year_to": int(end_year) if end_year.strip() else None,
               "topics": [s.strip() for s in topics_text.replace("，", ",").split(",") if s.strip()]}
    if filters["year_from"] is not None and filters["year_to"] is not None and filters["year_from"] > filters["year_to"]:
        raise ValueError()
except ValueError:
    st.error("年份须为整数，且起始年份不能大于结束年份。")
    st.stop()


def doc_card(doc):
    st.markdown("**" + doc["title"] + "**")
    st.write(" · ".join(["、".join(doc.get("authors", [])) or "作者未标注", str(doc.get("year") or "年份未标注"),
                         "、".join(doc.get("topics", [])) or "主题未标注"]))
    if doc.get("source_url"):
        st.write("来源：", doc["source_url"])


progress_target = None
STAGES = {"queued": "排队等待", "waiting": "等待馆藏读取", "planning": "理解问题与生成中英文检索词",
          "retrieval": "检索相关文献", "evidence_selection": "重排并选择正文及相邻证据",
          "generation": "模型正在整合回答", "repair": "修复回答格式与引用", "validation": "核验引用与问题要点覆盖",
          "citation_grounding": "定位支持回答的原文句子",
          "coverage_check": "核对回答与问题要点的关联",
          "done": "处理完成", "error": "处理失败"}


def draw_progress(job):
    if progress_target is None:
        return
    progress_target.empty()
    # Static status blocks are replaced on every poll, including repeated stages.
    # Clearing a placeholder does not release explicit keys within the same run.
    with progress_target.container(border=True):
        st.markdown("**回答进度**")
        st.write(STAGES.get(job["stage"], job["stage"]))
        st.caption(f"已用时 {job['elapsed_seconds']:.1f} 秒")
        for stage in dict.fromkeys(job.get("stages", [])):
            if stage != job["stage"]:
                st.caption("✓ " + STAGES.get(stage, stage))
        if job["stage"] in {"generation", "repair"}:
            st.caption("正在等待模型返回，期间会持续更新用时。")
        if job["stage"] == "done":
            st.caption("请在左侧阅读回答；原文证据可展开核对。")


def idle_progress():
    if progress_target is not None:
        progress_target.empty()
        with progress_target.container(border=True):
            st.markdown("**回答进度**")
            st.caption("提交问答后，这里会显示后台实际处理阶段。")


def ask_with_progress(body):
    st.session_state.pop("last_progress", None)
    draw_progress({"job_id": str(time.monotonic_ns()), "stage": "queued", "stages": [], "elapsed_seconds": 0})
    value = api("POST", "/ask/jobs", json=body)
    if not value:
        idle_progress()
        return None
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        job = api("GET", "/ask/jobs/" + value["job_id"])
        if not job:
            st.session_state.pop("last_progress", None)
            idle_progress()
            return None
        st.session_state["last_progress"] = job
        draw_progress(job)
        if job["answer"] is not None:
            return job["answer"]
        time.sleep(0.5)
    st.warning("本次等待超过 5 分钟，请检查后端状态。任务可能仍在后台处理。")
    return None


def show_answer(answer):
    st.session_state["last_request_id"] = answer["request_id"]
    plan = answer["query_plan"]
    with st.expander("系统理解", expanded=False):
        st.write("检索表达：", plan["rewritten_query"])
        if plan.get("english_query") and answer.get("diagnostics", {}).get("multi_query"):
            st.write("英文检索表达：", plan["english_query"])
        st.write("意图：", {"find": "查找", "explain": "解释", "compare": "比较", "clarify": "需要澄清"}[plan["intent"]])
    status = answer["status"]
    if status == "error":
        st.error(answer["error"]["message"])
        st.caption("错误标识：" + answer["error"]["code"])
    elif status == "needs_clarification":
        st.info(answer["clarification_question"])
        with st.form("clarification"):
            options = answer["clarification_options"]
            choice = st.radio("请选择", options) if options else st.text_input("补充说明")
            if st.form_submit_button("补充后重新提问") and choice:
                value = ask_with_progress({"question": clarified_question(plan["original_query"], choice),
                                           "filters": st.session_state.get("answer_filters", filters), "history": []})
                if value:
                    st.session_state["answer"] = value
                    st.session_state.pop("selected_evidence", None)
                    st.rerun()
    elif status == "insufficient_evidence":
        st.warning("当前馆藏证据不足，无法据此给出可靠结论。")
    numbers = citation_numbers(answer)
    diagnostics = answer.get('diagnostics', {})
    if diagnostics.get('retrieval_calls') and 'selected_chunks' in diagnostics:
        st.caption(f"检索去重 {diagnostics['retrieved_unique_chunks']} 个片段 · 重排候选 {diagnostics['candidate_chunks']} 个 · 选入上下文 {diagnostics['selected_chunks']} 个 · 最终引用 {diagnostics['cited_chunks']} 个")
    if answer["claims"]:
        st.markdown("### 回答")
        claims = {c["claim_id"]: c for c in answer["claims"]}
        sections = answer.get("answer_sections") or [{"heading": "", "claim_ids": list(claims)}]
        for section in sections:
            if section["heading"]:
                st.markdown("**" + section["heading"] + "**")
            sentences = []
            for cid in section["claim_ids"]:
                claim = claims[cid]
                sentences.append(claim_html(claim, answer["evidence"], numbers, base, answer["index_version"]))
            st.markdown('<p style="line-height:1.9">' + " ".join(sentences) + '</p>', unsafe_allow_html=True)
        for limitation in answer["limitations"]:
            st.caption("回答范围：" + limitation)
        if answer.get('coverage'):
            with st.expander('问题要点与回答范围'):
                for row in answer['coverage']:
                    st.write(row['requirement'])
                    if row['claim_indices']:
                        st.caption('可对照正文中的相关说明' + ('；仍有缺口：' + row['gap'] if row['gap'] else ''))
                    else:
                        st.caption('资料缺口：' + row['gap'])
        st.markdown("**核对原文**")
        for eid in numbers:
            if st.button(f"[{numbers[eid]}] 查看原文", key="cite_" + eid):
                st.session_state["selected_evidence"] = eid
    for evidence in answer["evidence"]:
        eid = evidence["evidence_id"]
        highlights = [span for claim in answer["claims"] for citation in claim.get("citations", [])
                      if citation["evidence_id"] == eid for span in citation["highlights"]]
        with st.expander(f"[{numbers[eid]}] {evidence['title']} · PDF 第 {evidence['pdf_page']} 页",
                         expanded=st.session_state.get("selected_evidence") == eid):
            st.markdown('<div style="white-space:pre-wrap;line-height:1.9">' + marked_text(evidence["quote"], highlights) + '</div>', unsafe_allow_html=True)
            if not highlights:
                st.caption("此回答未包含句子定位信息，重新提问后可使用句子高亮。")
            st.caption("、".join(evidence["authors"]) + " · " + str(evidence["year"] or "年份未标注"))
            st.link_button("打开 PDF 原文件（尝试定位该页）", base.rstrip("/") + evidence["file_url"])
            unique = list({(s['start'], s['end']): s for s in highlights}.values())[:6]
            st.link_button("查看高亮原文与 PDF 原页", source_url(base, evidence, unique, answer["index_version"]))
            st.caption(f"PDF 文件第 {evidence['pdf_page']} 页。回答角标按当前结论定位；此处汇总本片段的引用句子。")
    if answer["related_documents"]:
        st.markdown("**相关文献**")
        for doc in answer["related_documents"]:
            st.link_button(doc["title"], base.rstrip("/") + f"/documents/{quote(doc['doc_id'], safe='')}/file")
    if not answer["claims"]:
        for limitation in answer["limitations"]:
            st.caption("说明：" + limitation)


if page == "馆藏展示":
    st.markdown('<div class="library-hero"><small>EXPLORE THE COLLECTION</small><h2>从一篇文献，开启新的发现</h2><p>浏览学科馆藏，阅读原始文献，让每一次提问都有据可依。</p></div>', unsafe_allow_html=True)
    params = [(k, v) for k, v in filters.items() if k != "topics" and v is not None]
    params += [("topics", t) for t in filters["topics"]]
    result = api("GET", "/documents", params=params)
    if result:
        documents = result["documents"]
        if section == "馆藏文献分类":
            st.subheader("馆藏文献分类")
            counts, pending = domain_counts(documents)
            columns = st.columns(4)
            columns[0].metric("馆藏文献", f"{len(documents)} 篇")
            for column, (domain, count) in zip(columns[1:], counts.items()):
                column.metric(domain, f"{count} 篇")
            chart, description = st.columns([1.3, 1])
            with chart:
                if any(counts.values()):
                    st.vega_lite_chart({"data": {"values": [{"学科": k, "篇数": v} for k, v in counts.items()]},
                        "mark": {"type": "arc", "outerRadius": {"expr": "max(0, min(140, width / 2 - 1, height / 2 - 1))"}, "stroke": "white", "strokeWidth": 2},
                        "encoding": {"theta": {"field": "篇数", "type": "quantitative"},
                            "color": {"field": "学科", "type": "nominal", "scale": {"domain": list(DOMAINS), "range": ["#247f87", "#e9aa58", "#8072b2"]}, "legend": {"orient": "bottom", "title": None}},
                            "tooltip": [{"field": "学科"}, {"field": "篇数", "type": "quantitative"}]},
                        "height": 340}, width="stretch")
                else:
                    st.info("暂无已分类文献，上传时可指定所属学科。")
            with description:
                st.markdown("#### 馆藏的三个方向")
                st.write("**自然科学** · 数学、物理、生物、计算机与技术等。")
                st.write("**社会科学** · 经济、社会、政治、教育与管理等。")
                st.write("**哲学与人文科学** · 哲学、历史、文学与艺术等。")
                st.caption("统计范围为当前筛选结果。优先使用学科标签；旧资料按题名和主题辅助归类。")
                if pending:
                    st.caption(f"另有 {pending} 篇待分类，未计入饼图。")
            chosen = st.selectbox("浏览所属学科", ["全部", *DOMAINS, "待分类"])
            visible = [d for d in documents if chosen == "全部" or (discipline(d) or "待分类") == chosen]
            st.caption(f"当前显示 {len(visible)} 篇文献")
            for doc in visible:
                with st.container(border=True):
                    doc_card(doc)
                    st.link_button("阅读原文 ↗", base.rstrip("/") + f"/documents/{quote(doc['doc_id'], safe='')}/file")
        else:
            st.subheader("热门电子文献资源")
            st.caption("精选馆藏推荐 · 封面采用文献 PDF 首页，点击封面阅读原文。当前未统计阅读热度，展示顺序不代表访问量排名。")
            if not documents:
                st.info("暂无可用文献，请在“上传与管理”添加 PDF。")
            columns = st.columns(3)
            for i, doc in enumerate(sorted(documents, key=lambda d: (-(d.get("year") or 0), d["title"]))):
                with columns[i % 3]:
                    st.markdown(cover_card(doc, base), unsafe_allow_html=True)
elif page == "搜索与问答":
    answer_column, progress_column = st.columns([3.4, 1.25])
    progress_target = progress_column.empty()
    if st.session_state.get("last_progress"):
        draw_progress(st.session_state["last_progress"])
    else:
        idle_progress()
    with answer_column:
        st.subheader("搜索与问答")
        with st.form("query"):
            question = st.text_area("想查找或了解什么？", max_chars=2000)
            action = st.radio("操作", ["搜索", "问答"], horizontal=True)
            mode = st.selectbox("搜索方式", ["keyword", "vector", "hybrid"], index=2,
                                format_func={"keyword": "关键词检索", "vector": "语义检索", "hybrid": "混合检索"}.get,
                                help="用于“搜索”操作；问答会自动组织检索。")
            submitted = st.form_submit_button("提交", on_click=reset_question, args=(st.session_state,))
        if submitted:
            st.session_state.pop("answer", None)
            st.session_state.pop("search_result", None)
            st.session_state.pop("selected_evidence", None)
            if action == "搜索":
                value = api("POST", "/search", json={"query": question, "filters": filters, "mode": mode, "top_k": 20})
                if value:
                    st.session_state["search_result"] = value
            else:
                value = ask_with_progress({"question": question, "filters": filters, "history": []})
                if value:
                    st.session_state["answer"] = value
                    st.session_state["answer_filters"] = filters
        result = st.session_state.get("search_result")
        if result:
            st.caption(f"{len(result['documents'])} 篇文献 · {len(result['hits'])} 个片段")
            for doc in result["documents"]:
                with st.container(border=True):
                    doc_card(doc)
                    st.caption(f"最佳排名：{doc['best_rank']}")
                    st.write(doc["preview"])
            for hit in result["hits"]:
                chunk = hit["chunk"]
                with st.expander(f"片段 {hit['rank']} · {chunk['document']['title']} · PDF 第 {chunk['pdf_page']} 页"):
                    st.write(chunk["text"])
                    st.link_button("打开该页", base.rstrip("/") + f"/documents/{chunk['doc_id']}/file#page={chunk['pdf_page']}")
                    st.caption("页号按 PDF 文件计数；定位由浏览器决定，未实现高亮。")
        if st.session_state.get("answer"):
            show_answer(st.session_state["answer"])
else:
    st.subheader("上传与管理")
    if section == "系统设置":
        st.caption("运行模式、模型和索引信息集中在此处，供维护时查看。")
        st.write("当前运行模式：", "真实服务（REAL）" if health["mode"] == "real" else "演示服务（MOCK）")
        if health["mode"] == "mock":
            st.warning("MOCK 使用合成资料和脚本问答，仅用于演示流程。")
        with st.expander("模式切换说明"):
            st.write("运行模式由后端启动配置决定。修改 APP_MODE 为 real（真实）或 mock（演示），并使用对应的 DATA_DIR 后重启后端；真实服务还需配置模型密钥。")
            st.caption("切换前请等待当前问答和上传完成。两种模式使用各自的数据目录。")
        st.write("当前模型：", health["active_models"])
        st.write("当前索引：", health["index_version"] or "暂无")
        for issue in health["issues"]:
            st.warning(f"{issue['component']}：{issue['message']}（{issue['code']}）")
        with st.expander("详细运行配置"):
            st.json(health["configuration"])
            if health.get("manifest"):
                st.json(health["manifest"])
        st.stop()
    if section == "文献管理":
        st.caption("查看已上传文献及其处理状态。")
        result = api("GET", "/documents", params={"include_nonready": "true"})
        if result:
            st.caption(f"共 {len(result['documents'])} 篇文献")
            for doc in result["documents"]:
                with st.container(border=True):
                    doc_card(doc)
                    st.caption("所属学科：" + (discipline(doc) or "待分类") + " · 状态：" + document_status(doc))
                    if doc.get("error_code"):
                        st.error(doc.get("error_message") or "文献处理未完成")
                    st.link_button("阅读原文", base.rstrip("/") + f"/documents/{quote(doc['doc_id'], safe='')}/file")
        st.stop()
    st.subheader("上传 PDF")
    st.caption("选择 PDF，自动识别标题和作者；核对文献信息后，即可加入馆藏。")
    use_metadata_api = st.toggle("增强识别（推荐）", value=True,
                                 help="使用已配置的 API 辅助识别；学科先按关键词判断，未匹配时由 LLM 辅助分类。会发送 PDF 前两页的图像和文字；关闭后仅在本机识别。")
    use_lookup = st.toggle("联网补全出版资料", value=False, disabled=not use_metadata_api,
                           help="增强识别成功后，将题名和前两位作者姓名发送至 Crossref 查询期刊或会议出版记录，不发送 PDF。补充相关出版来源；仅确认同一出版版本时补缺失年份。年份应对应当前 PDF，预印本可填公开或修订年份。结果需核对。修改选项后请点击重新识别。")
    file = st.file_uploader(f"上传 PDF（单份最大 {health['configuration']['max_upload_mb']} MB）", type=["pdf"], key="upload_pdf",
                            max_upload_size=health['configuration']['max_upload_mb'])
    retry_metadata = st.button("重新识别文献信息", disabled=file is None, help="重新预填当前文件的信息，会替换表单中的识别字段。")
    if file is None and "upload_fingerprint" in st.session_state:
        reset_upload(st.session_state, keep_file=True)
    if file is not None:
        fingerprint = file.name + ":" + hashlib.sha256(file.getvalue()).hexdigest()
        if retry_metadata or st.session_state.get("upload_fingerprint") != fingerprint:
            reset_upload(st.session_state, keep_file=True)
            st.session_state["upload_fingerprint"] = fingerprint
            preview = document_with_progress("/documents/metadata/jobs",
                files={"file": (file.name, file.getvalue(), "application/pdf")},
                data={"use_api": str(use_metadata_api).lower(), "use_lookup": str(use_lookup and use_metadata_api).lower()})
            st.session_state["upload_preview"] = preview
            metadata = preview["metadata"] if preview else {}
            values = dict(upload_title=metadata.get("title") or "", upload_authors="\n".join(metadata.get("authors", [])),
                          upload_year=str(metadata["year"]) if metadata.get("year") is not None else "",
                          upload_language=metadata.get("language", "unknown"), upload_source=metadata.get("source_url") or "",
                          upload_topics="", upload_rights="待人工确认", upload_domain=discipline(metadata))
            for key, value in values.items():
                st.session_state[key] = value
        preview = st.session_state.get("upload_preview")
        if preview:
            with st.expander("识别结果与来源", expanded=True):
                for warning in preview["warnings"]:
                    st.caption(warning)
                classification = preview.get("discipline_classification", {})
                if classification.get("status") == "classified":
                    method = {"keyword": "关键词匹配", "explicit": "已有学科标签",
                              "llm_page_classification": "LLM 辅助分类"}.get(classification["method"], "自动分类")
                    st.write("所属学科：" + classification["value"] + "（" + method + "）")
                    if classification.get("excerpt"):
                        st.caption(f"PDF 第 {classification['pdf_page']} 页 · " + classification["excerpt"])
                    if classification.get("reason"):
                        st.caption(classification["reason"])
                else:
                    st.caption("暂未确定所属学科，可在下方选择，或开启增强识别后重新识别。")
                labels = {"title": "标题", "authors": "作者", "year": "版本年份", "language": "语言", "source_url": "来源"}
                methods = {"pdf_metadata": "PDF 自带信息", "first_page_layout": "首页标题排版",
                           "first_page_text": "首页文字", "document_date_candidate": "正文日期候选",
                           "document_identifier": "正文中的文献标识", "text_language_heuristic": "前两页文字",
                           "api_page_recognition": "API 页面识别（待核对）",
                           "bibliographic_lookup": "外部出版记录（待核对）"}
                for field, origin in preview["field_sources"].items():
                    st.write(labels[field] + "：" + methods[origin["method"]])
                    if field == "year" and origin.get("date_type"):
                        date_labels = {"issue": "卷期年份", "version": "文件版本戳", "revision": "修订日期", "preprint": "预印本公开日期",
                                       "submission": "投稿日期", "acceptance": "接收日期", "publication": "出版日期",
                                       "copyright": "版权年份", "published-print": "印刷出版日期",
                                       "published-online": "在线出版日期", "published": "出版日期"}
                        st.caption("日期依据：" + date_labels.get(origin["date_type"], origin["date_type"]))
                    if origin["method"] == "api_page_recognition":
                        st.caption(f"PDF 第 {origin['pdf_page']} 页 · " + origin["excerpt"])
                    elif origin["method"] == "bibliographic_lookup":
                        st.caption(origin["excerpt"])
                        st.link_button("查看该字段的出版记录", origin["record_url"], key="metadata_origin_" + field)
                enrichment = preview.get("bibliographic_enrichment", {})
                if enrichment.get("year_decision") in {"version_not_confirmed", "registry_dates_differ"}:
                    for record in enrichment.get("candidates", []):
                        dates = "、".join(str(d["year"]) + "（" + d["kind"] + "）" for d in record["dates"])
                        st.caption("相关出版记录日期：" + (dates or "未提供") + "；未自动用作当前版本年份。")
                        st.link_button("核对相关出版记录", record["record_url"], key="metadata_related_publication")
                if enrichment.get("conflicts"):
                    st.warning("现有信息与外部记录存在差异，已保留现有值，请核对后修改。")
                    for conflict in enrichment["conflicts"]:
                        st.write(labels[conflict["field"]] + "：当前为 " + str(conflict["existing"])
                                 + "，出版记录为 " + str(conflict["external"]))
    if st.session_state.get("upload_success"):
        st.success(st.session_state.pop("upload_success"))
    if "upload_rights" not in st.session_state:
        st.session_state["upload_rights"] = "待人工确认"
    with st.form("upload", clear_on_submit=False):
        title = st.text_input("标题（留空则标待核验）", key="upload_title")
        authors = st.text_area("作者（每行一位）", key="upload_authors")
        year = st.text_input("版本年份（可留空）", key="upload_year")
        domain = st.selectbox("所属学科", DOMAINS, index=None, placeholder="请选择文献所属学科", key="upload_domain")
        topics = st.text_input("主题（逗号分隔）", key="upload_topics")
        language = st.selectbox("语言", ["zh", "en", "mixed", "unknown"], index=3, key="upload_language",
                                format_func={"zh": "中文", "en": "英文", "mixed": "中英混合", "unknown": "未确定"}.get)
        source = st.text_input("来源链接（可选）", key="upload_source")
        rights = st.text_input("使用说明", key="upload_rights")
        if st.form_submit_button("导入文献"):
            if file is None:
                st.error("请先选择 PDF 文件。")
            elif domain is None:
                st.error("请选择文献所属学科。")
            else:
                try:
                    metadata = {"authors": [x.strip() for x in authors.splitlines() if x.strip()],
                                "year": int(year) if year.strip() else None,
                                "topics": [domain] + [x.strip() for x in topics.replace("，", ",").split(",") if x.strip() and x.strip() not in DOMAINS],
                                "language": language, "rights_note": rights}
                    if title.strip():
                        metadata["title"] = title.strip()
                    if source.strip():
                        metadata["source_url"] = source.strip()
                    value = document_with_progress("/documents/jobs", files={"file": (file.name, file.getvalue(), "application/pdf")},
                                data={"metadata_json": json.dumps(metadata, ensure_ascii=False)})
                    if value:
                        st.session_state["upload_success"] = "文献已加入馆藏：" + value["document"]["title"]
                        st.rerun()
                except ValueError:
                    st.error("年份须为整数或留空。")
