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
from dlrag.ui.library import DOMAINS, STYLE, cover_card, discipline, domain_counts, document_status, display_topics
from dlrag.ui.state import reset_question, reset_upload, reset_view
from dlrag.shared.i18n import t, labels as widget_labels, error_message, system_message
from dlrag.ui.language import language_selector

language_selector()
st.set_page_config(page_title=t('专题数字图书馆'), page_icon="📚", layout="wide")
st.markdown(STYLE, unsafe_allow_html=True)
st.title(t('专题数字图书馆'))
st.caption(t('查找文献 · 依据原文提问 · 核对每一条引用'))
base = os.environ.get("API_BASE_URL") or dotenv_values(".env").get("API_BASE_URL") or "http://127.0.0.1:8000"


def api(method, path, **kwargs):
    value = call_api(base, method, path, **kwargs)
    if "_failure" in value:
        st.error(error_message(value["_failure"]))
        st.caption(t('错误标识：') + value["_failure"]["code"])
        return None
    return value


DOCUMENT_STAGES = {
    "queued": (5, t('等待处理')), "file_received": (12, t('已接收 PDF')),
    "local_reading": (25, t('读取文献信息')), "page_preparation": (35, t('准备页面图像')),
    "api_recognition": (55, t('API 正在识别标题、作者等信息')),
    "bibliographic_lookup": (95, t('查询出版资料，补全缺失信息')),
    "metadata_validation": (90, t('校验识别结果')), "waiting": (20, t('等待馆藏处理')),
    "document_parsing": (40, t('解析文献正文')), "document_processing": (65, t('处理文献，准备搜索')),
    "document_saving": (95, t('保存文献信息')), "done": (100, t('处理完成')), "error": (0, t('处理未完成'))}


def document_with_progress(path, **kwargs):
    bar = st.progress(0, text=t('正在提交 PDF…'))
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
        percent, label = DOCUMENT_STAGES.get(job["stage"], (10, t('处理中')))
        bar.progress(percent, text=label)
        detail.caption(t('已用时 {p0:.1f} 秒 · 按实际处理阶段显示进度', p0=job['elapsed_seconds']))
        if job["stage"] == "error":
            st.error(error_message(job["error"]))
            return None
        if job["stage"] == "done":
            if job["result"].get("api_assistance", {}).get("status") in {"failed", "unavailable"}:
                bar.progress(100, text=t('本机识别完成，增强识别未成功'))
            return job["result"]
        time.sleep(0.35)
    st.warning(t('处理超过 5 分钟，后台可能仍在继续，请到文献管理查看结果后再重试。'))
    return None


health = api("GET", "/health")
if not health:
    st.info(t('先在另一个终端启动后端：python -m dlrag.api.main'))
    st.stop()
if health["status"] != "ready":
    st.info(t('部分服务暂不可用，可在“上传与管理 → 系统设置”查看详情。'))

st.sidebar.markdown(t('### 📚 阅读与发现'))
st.sidebar.caption(t('专题数字图书馆 · 您的文献工作台'))
page = st.sidebar.radio(t('功能'), ["馆藏展示", "搜索与问答", "上传与管理"],
                        key="navigation_page", format_func=widget_labels(["馆藏展示", "搜索与问答", "上传与管理"]), on_change=reset_view, args=(st.session_state,))
section = None
if page == "馆藏展示":
    section = st.sidebar.radio(t('馆藏导航'), ["馆藏文献分类", "热门电子文献资源"],
                               key="library_section", format_func=widget_labels(["馆藏文献分类", "热门电子文献资源"]), on_change=reset_view, args=(st.session_state,))
elif page == "上传与管理":
    section = st.sidebar.radio(t('管理导航'), ["上传文献", "文献管理", "系统设置"],
                               key="management_section", format_func=widget_labels(["上传文献", "文献管理", "系统设置"]), on_change=reset_view, args=(st.session_state,))
start_year = end_year = topics_text = ""
if page in {"馆藏展示", "搜索与问答"}:
    with st.sidebar.expander(t('筛选文献'), expanded=False):
        start_year = st.text_input(t('起始年份'), placeholder=t('不限'), key='filter_year_from')
        end_year = st.text_input(t('结束年份'), placeholder=t('不限'), key='filter_year_to')
        topics_text = st.text_input(t('主题（逗号分隔）'), placeholder=t('信息检索,数字图书馆'), key='filter_topics')
try:
    filters = {"year_from": int(start_year) if start_year.strip() else None,
               "year_to": int(end_year) if end_year.strip() else None,
               "topics": [s.strip() for s in topics_text.replace("，", ",").split(",") if s.strip()]}
    if filters["year_from"] is not None and filters["year_to"] is not None and filters["year_from"] > filters["year_to"]:
        raise ValueError()
except ValueError:
    st.error(t('年份须为整数，且起始年份不能大于结束年份。'))
    st.stop()


def doc_card(doc):
    st.markdown("**" + doc["title"] + "**")
    st.write(" · ".join(["、".join(doc.get("authors", [])) or t('作者未标注'), str(doc.get("year") or t('年份未标注')),
                         display_topics(doc.get("topics", [])) or t('主题未标注')]))
    if doc.get("source_url"):
        st.write(t('来源：'), doc["source_url"])


progress_target = None
STAGES = {"queued": t('排队等待'), "waiting": t('等待馆藏读取'), "planning": t('理解问题与生成中英文检索词'),
          "retrieval": t('检索相关文献'), "evidence_selection": t('重排并选择正文及相邻证据'),
          "generation": t('模型正在整合回答'), "repair": t('修复回答格式与引用'), "validation": t('核验引用与问题要点覆盖'),
          "citation_grounding": t('定位支持回答的原文句子'),
          "coverage_check": t('核对回答与问题要点的关联'),
          "done": t('处理完成'), "error": t('处理失败')}


def draw_progress(job):
    if progress_target is None:
        return
    progress_target.empty()
    # Static status blocks are replaced on every poll, including repeated stages.
    # Clearing a placeholder does not release explicit keys within the same run.
    with progress_target.container(border=True):
        st.markdown(t('**回答进度**'))
        st.write(STAGES.get(job["stage"], job["stage"]))
        st.caption(t('已用时 {p0:.1f} 秒', p0=job['elapsed_seconds']))
        for stage in dict.fromkeys(job.get("stages", [])):
            if stage != job["stage"]:
                st.caption("✓ " + STAGES.get(stage, stage))
        if job["stage"] in {"generation", "repair"}:
            st.caption(t('正在等待模型返回，期间会持续更新用时。'))
        if job["stage"] == "done":
            st.caption(t('请在左侧阅读回答；原文证据可展开核对。'))


def idle_progress():
    if progress_target is not None:
        progress_target.empty()
        with progress_target.container(border=True):
            st.markdown(t('**回答进度**'))
            st.caption(t('提交问答后，这里会显示后台实际处理阶段。'))


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
    st.warning(t('本次等待超过 5 分钟，请检查后端状态。任务可能仍在后台处理。'))
    return None


def show_answer(answer):
    st.session_state["last_request_id"] = answer["request_id"]
    plan = answer["query_plan"]
    with st.expander(t('系统理解'), expanded=False):
        st.write(t('检索表达：'), plan["rewritten_query"])
        if plan.get("english_query") and answer.get("diagnostics", {}).get("multi_query"):
            st.write(t('英文检索表达：'), plan["english_query"])
        st.write(t('意图：'), {"find": t('查找'), "explain": t('解释'), "compare": t('比较'), "clarify": t('需要澄清')}[plan["intent"]])
    status = answer["status"]
    if status == "error":
        st.error(error_message(answer["error"]))
        st.caption(t('错误标识：') + answer["error"]["code"])
    elif status == "needs_clarification":
        st.info(answer["clarification_question"])
        with st.container():
            options = answer["clarification_options"]
            choice = st.radio(t('请选择'), options) if options else st.text_input(t('补充说明'))
            if st.button(t('补充后重新提问')) and choice:
                value = ask_with_progress({"question": clarified_question(plan["original_query"], choice),
                                           "filters": st.session_state.get("answer_filters", filters), "history": []})
                if value:
                    st.session_state["answer"] = value
                    st.session_state.pop("selected_evidence", None)
                    st.rerun()
    elif status == "insufficient_evidence":
        st.warning(t('当前馆藏证据不足，无法据此给出可靠结论。'))
    numbers = citation_numbers(answer)
    diagnostics = answer.get('diagnostics', {})
    if diagnostics.get('retrieval_calls') and 'selected_chunks' in diagnostics:
        st.caption(t('检索去重 {p0} 个片段 · 重排候选 {p1} 个 · 选入上下文 {p2} 个 · 最终引用 {p3} 个', p0=diagnostics['retrieved_unique_chunks'], p1=diagnostics['candidate_chunks'], p2=diagnostics['selected_chunks'], p3=diagnostics['cited_chunks']))
    if answer["claims"]:
        st.markdown(t('### 回答'))
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
            st.caption(t('回答范围：') + limitation)
        if answer.get('coverage'):
            with st.expander(t('问题要点与回答范围')):
                for row in answer['coverage']:
                    st.write(row['requirement'])
                    if row['claim_indices']:
                        st.caption(t('可对照正文中的相关说明') + (t('；仍有缺口：') + row['gap'] if row['gap'] else ''))
                    else:
                        st.caption(t('资料缺口：') + row['gap'])
        st.markdown(t('**核对原文**'))
        for eid in numbers:
            if st.button(t('[{p0}] 查看原文', p0=numbers[eid]), key="cite_" + eid):
                st.session_state["selected_evidence"] = eid
    for evidence in answer["evidence"]:
        eid = evidence["evidence_id"]
        highlights = [span for claim in answer["claims"] for citation in claim.get("citations", [])
                      if citation["evidence_id"] == eid for span in citation["highlights"]]
        with st.expander(t('[{p0}] {p1} · PDF 第 {p2} 页', p0=numbers[eid], p1=evidence['title'], p2=evidence['pdf_page']),
                         expanded=st.session_state.get("selected_evidence") == eid):
            st.markdown('<div style="white-space:pre-wrap;line-height:1.9">' + marked_text(evidence["quote"], highlights) + '</div>', unsafe_allow_html=True)
            if not highlights:
                st.caption(t('此回答未包含句子定位信息，重新提问后可使用句子高亮。'))
            st.caption("、".join(evidence["authors"]) + " · " + str(evidence["year"] or t('年份未标注')))
            st.link_button(t('打开 PDF 原文件（尝试定位该页）'), base.rstrip("/") + evidence["file_url"])
            unique = list({(s['start'], s['end']): s for s in highlights}.values())[:6]
            st.link_button(t('查看高亮原文与 PDF 原页'), source_url(base, evidence, unique, answer["index_version"]))
            st.caption(t('PDF 文件第 {p0} 页。回答角标按当前结论定位；此处汇总本片段的引用句子。', p0=evidence['pdf_page']))
    if answer["related_documents"]:
        st.markdown(t('**相关文献**'))
        for doc in answer["related_documents"]:
            st.link_button(doc["title"], base.rstrip("/") + f"/documents/{quote(doc['doc_id'], safe='')}/file")
    if not answer["claims"]:
        for limitation in answer["limitations"]:
            st.caption(t('说明：') + limitation)


if page == "馆藏展示":
    st.markdown(t('<div class="library-hero"><small>EXPLORE THE COLLECTION</small><h2>从一篇文献，开启新的发现</h2><p>浏览学科馆藏，阅读原始文献，让每一次提问都有据可依。</p></div>'), unsafe_allow_html=True)
    params = [(k, v) for k, v in filters.items() if k != "topics" and v is not None]
    params += [("topics", t) for t in filters["topics"]]
    result = api("GET", "/documents", params=params)
    if result:
        documents = result["documents"]
        if section == "馆藏文献分类":
            st.subheader(t('馆藏文献分类'))
            counts, pending = domain_counts(documents)
            columns = st.columns(4)
            columns[0].metric(t('馆藏文献'), t('{p0} 篇', p0=len(documents)))
            for column, (domain, count) in zip(columns[1:], counts.items()):
                column.metric(t(domain), t('{p0} 篇', p0=count))
            chart, description = st.columns([1.3, 1])
            with chart:
                if any(counts.values()):
                    st.vega_lite_chart({"data": {"values": [{t('学科'): t(k), t('篇数'): v} for k, v in counts.items()]},
                        "mark": {"type": "arc", "outerRadius": 140, "stroke": "white", "strokeWidth": 2},
                        "encoding": {"theta": {"field": t('篇数'), "type": "quantitative"},
                            "color": {"field": t('学科'), "type": "nominal", "scale": {"domain": [t(d) for d in DOMAINS], "range": ["#247f87", "#e9aa58", "#8072b2"]}, "legend": {"orient": "bottom", "title": None}},
                            "tooltip": [{"field": t('学科')}, {"field": t('篇数'), "type": "quantitative"}]},
                        "height": 340}, width="stretch")
                else:
                    st.info(t('暂无已分类文献，上传时可指定所属学科。'))
            with description:
                st.markdown(t('#### 馆藏的三个方向'))
                st.write(t('**自然科学** · 数学、物理、生物、计算机与技术等。'))
                st.write(t('**社会科学** · 经济、社会、政治、教育与管理等。'))
                st.write(t('**哲学与人文科学** · 哲学、历史、文学与艺术等。'))
                st.caption(t('统计范围为当前筛选结果。优先使用学科标签；旧资料按题名和主题辅助归类。'))
                if pending:
                    st.caption(t('另有 {p0} 篇待分类，未计入饼图。', p0=pending))
            chosen = st.selectbox(t('浏览所属学科'), ["全部", *DOMAINS, "待分类"], key='browse_domain', format_func=widget_labels(["全部", *DOMAINS, "待分类"]))
            visible = [d for d in documents if chosen == "全部" or (discipline(d) or "待分类") == chosen]
            st.caption(t('当前显示 {p0} 篇文献', p0=len(visible)))
            for doc in visible:
                with st.container(border=True):
                    doc_card(doc)
                    st.link_button(t('阅读原文 ↗'), base.rstrip("/") + f"/documents/{quote(doc['doc_id'], safe='')}/file")
        else:
            st.subheader(t('热门电子文献资源'))
            st.caption(t('精选馆藏推荐 · 封面采用文献 PDF 首页，点击封面阅读原文。当前未统计阅读热度，展示顺序不代表访问量排名。'))
            if not documents:
                st.info(t('暂无可用文献，请在“上传与管理”添加 PDF。'))
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
        st.subheader(t('搜索与问答'))
        with st.container():
            question = st.text_area(t('想查找或了解什么？'), max_chars=2000, key='query_question')
            action = st.radio(t('操作'), ["搜索", "问答"], horizontal=True, key='query_action', format_func=widget_labels(["搜索", "问答"]))
            mode = st.selectbox(t('搜索方式'), ["keyword", "vector", "hybrid"], index=2,
                                format_func={"keyword": t('关键词检索'), "vector": t('语义检索'), "hybrid": t('混合检索')}.get,
                                help=t('用于“搜索”操作；问答会自动组织检索。'), key='query_mode')
            submitted = st.button(t('提交'), on_click=reset_question, args=(st.session_state,))
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
            st.caption(t('{p0} 篇文献 · {p1} 个片段', p0=len(result['documents']), p1=len(result['hits'])))
            for doc in result["documents"]:
                with st.container(border=True):
                    doc_card(doc)
                    st.caption(t('最佳排名：{p0}', p0=doc['best_rank']))
                    st.write(doc["preview"])
            for hit in result["hits"]:
                chunk = hit["chunk"]
                with st.expander(t('片段 {p0} · {p1} · PDF 第 {p2} 页', p0=hit['rank'], p1=chunk['document']['title'], p2=chunk['pdf_page'])):
                    st.write(chunk["text"])
                    st.link_button(t('打开该页'), base.rstrip("/") + f"/documents/{chunk['doc_id']}/file#page={chunk['pdf_page']}")
                    st.caption(t('页号按 PDF 文件计数；定位由浏览器决定，未实现高亮。'))
        if st.session_state.get("answer"):
            show_answer(st.session_state["answer"])
else:
    st.subheader(t('上传与管理'))
    if section == "系统设置":
        st.subheader(t('系统设置'))
        st.caption(t('运行模式、模型和索引信息集中在此处，供维护时查看。'))
        st.write(t('当前运行模式：'), t('真实服务（REAL）') if health["mode"] == "real" else t('演示服务（MOCK）'))
        if health["mode"] == "mock":
            st.warning(t('MOCK 使用合成资料和脚本问答，仅用于演示流程。'))
        with st.expander(t('模式切换说明')):
            st.write(t('运行模式由后端启动配置决定。修改 APP_MODE 为 real（真实）或 mock（演示），并使用对应的 DATA_DIR 后重启后端；真实服务还需配置模型密钥。'))
            st.caption(t('切换前请等待当前问答和上传完成。两种模式使用各自的数据目录。'))
        st.write(t('当前模型：'), health["active_models"])
        st.write(t('当前索引：'), health["index_version"] or t('暂无'))
        for issue in health["issues"]:
            st.warning(issue["component"] + ": " + error_message(issue) + " (" + issue["code"] + ")")
        with st.expander(t('详细运行配置')):
            st.json(health["configuration"])
            if health.get("manifest"):
                st.json(health["manifest"])
        st.stop()
    if section == "文献管理":
        st.subheader(t('文献管理'))
        st.caption(t('查看已上传文献及其处理状态。'))
        result = api("GET", "/documents", params={"include_nonready": "true"})
        if result:
            st.caption(t('共 {p0} 篇文献', p0=len(result['documents'])))
            for doc in result["documents"]:
                with st.container(border=True):
                    doc_card(doc)
                    st.caption(t('所属学科：') + t(discipline(doc) or "待分类") + t(' · 状态：') + document_status(doc))
                    if doc.get("error_code"):
                        st.error(error_message({"code":doc["error_code"], "message":doc.get("error_message") or "文献处理未完成"}))
                    st.link_button(t('阅读原文'), base.rstrip("/") + f"/documents/{quote(doc['doc_id'], safe='')}/file")
        st.stop()
    st.subheader(t('上传 PDF'))
    st.caption(t('选择 PDF，自动识别标题和作者；核对文献信息后，即可加入馆藏。'))
    use_metadata_api = st.toggle(t('增强识别（推荐）'), value=True,
                                 help=t('使用已配置的 API 辅助识别；学科先按关键词判断，未匹配时由 LLM 辅助分类。会发送 PDF 前两页的图像和文字；关闭后仅在本机识别。'), key='metadata_assist')
    use_lookup = st.toggle(t('联网补全出版资料'), value=False, disabled=not use_metadata_api,
                           help=t('增强识别成功后，将题名和前两位作者姓名发送至 Crossref 查询期刊或会议出版记录，不发送 PDF。补充相关出版来源；仅确认同一出版版本时补缺失年份。年份应对应当前 PDF，预印本可填公开或修订年份。结果需核对。修改选项后请点击重新识别。'), key='metadata_lookup')
    file = st.file_uploader(t('上传 PDF（单份最大 {p0} MB）', p0=health['configuration']['max_upload_mb']), type=["pdf"], key="upload_pdf",
                            max_upload_size=health['configuration']['max_upload_mb'])
    retry_metadata = st.button(t('重新识别文献信息'), disabled=file is None, help=t('重新预填当前文件的信息，会替换表单中的识别字段。'), key='retry_metadata')
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
                          upload_topics="", upload_rights="", upload_domain=discipline(metadata))
            for key, value in values.items():
                st.session_state[key] = value
        preview = st.session_state.get("upload_preview")
        if preview:
            with st.expander(t('识别结果与来源'), expanded=True):
                for warning in preview["warnings"]:
                    st.caption(system_message(warning))
                classification = preview.get("discipline_classification", {})
                if classification.get("status") == "classified":
                    method = {"keyword": t('关键词匹配'), "explicit": t('已有学科标签'),
                              "llm_page_classification": t('LLM 辅助分类')}.get(classification["method"], t('自动分类'))
                    st.write(t('所属学科：') + t(classification["value"]) + "（" + method + "）")
                    if classification.get("excerpt"):
                        st.caption(t('PDF 第 {p0} 页 · ', p0=classification['pdf_page']) + classification["excerpt"])
                    if classification.get("reason"):
                        st.caption(classification["reason"])
                else:
                    st.caption(t('暂未确定所属学科，可在下方选择，或开启增强识别后重新识别。'))
                labels = {"title": t('标题'), "authors": t('作者'), "year": t('版本年份'), "language": t('语言'), "source_url": t('来源')}
                methods = {"pdf_metadata": t('PDF 自带信息'), "first_page_layout": t('首页标题排版'),
                           "first_page_text": t('首页文字'), "document_date_candidate": t('正文日期候选'),
                           "document_identifier": t('正文中的文献标识'), "text_language_heuristic": t('前两页文字'),
                           "api_page_recognition": t('API 页面识别（待核对）'),
                           "bibliographic_lookup": t('外部出版记录（待核对）')}
                for field, origin in preview["field_sources"].items():
                    st.write(labels[field] + "：" + methods[origin["method"]])
                    if field == "year" and origin.get("date_type"):
                        date_labels = {"issue": t('卷期年份'), "version": t('文件版本戳'), "revision": t('修订日期'), "preprint": t('预印本公开日期'),
                                       "submission": t('投稿日期'), "acceptance": t('接收日期'), "publication": t('出版日期'),
                                       "copyright": t('版权年份'), "published-print": t('印刷出版日期'),
                                       "published-online": t('在线出版日期'), "published": t('出版日期')}
                        st.caption(t('日期依据：') + date_labels.get(origin["date_type"], origin["date_type"]))
                    if origin["method"] == "api_page_recognition":
                        st.caption(t('PDF 第 {p0} 页 · ', p0=origin['pdf_page']) + origin["excerpt"])
                    elif origin["method"] == "bibliographic_lookup":
                        st.caption(origin["excerpt"])
                        st.link_button(t('查看该字段的出版记录'), origin["record_url"], key="metadata_origin_" + field)
                enrichment = preview.get("bibliographic_enrichment", {})
                if enrichment.get("year_decision") in {"version_not_confirmed", "registry_dates_differ"}:
                    for record in enrichment.get("candidates", []):
                        dates = "、".join(str(d["year"]) + "（" + d["kind"] + "）" for d in record["dates"])
                        st.caption(t('相关出版记录日期：') + (dates or t('未提供')) + t('；未自动用作当前版本年份。'))
                        st.link_button(t('核对相关出版记录'), record["record_url"], key="metadata_related_publication")
                if enrichment.get("conflicts"):
                    st.warning(t('现有信息与外部记录存在差异，已保留现有值，请核对后修改。'))
                    for conflict in enrichment["conflicts"]:
                        st.write(labels[conflict["field"]] + t('：当前为 ') + str(conflict["existing"])
                                 + t('，出版记录为 ') + str(conflict["external"]))
    if st.session_state.get("upload_success"):
        st.success(st.session_state.pop("upload_success"))
    if "upload_rights" not in st.session_state:
        st.session_state["upload_rights"] = ""
    with st.container():
        title = st.text_input(t('标题（留空则标待核验）'), key="upload_title")
        authors = st.text_area(t('作者（每行一位）'), key="upload_authors")
        year = st.text_input(t('版本年份（可留空）'), key="upload_year")
        domain = st.selectbox(t('所属学科'), DOMAINS, format_func=widget_labels(DOMAINS), index=None, placeholder=t('请选择文献所属学科'), key="upload_domain")
        topics = st.text_input(t('主题（逗号分隔）'), key="upload_topics")
        language = st.selectbox(t('语言'), ["zh", "en", "mixed", "unknown"], index=3, key="upload_language",
                                format_func={"zh": t('中文'), "en": t('英文'), "mixed": t('中英混合'), "unknown": t('未确定')}.get)
        source = st.text_input(t('来源链接（可选）'), key="upload_source")
        rights = st.text_input(t('使用说明'), key="upload_rights", placeholder=t("待人工确认"))
        if st.button(t('导入文献')):
            if file is None:
                st.error(t('请先选择 PDF 文件。'))
            elif domain is None:
                st.error(t('请选择文献所属学科。'))
            else:
                try:
                    metadata = {"authors": [x.strip() for x in authors.splitlines() if x.strip()],
                                "year": int(year) if year.strip() else None,
                                "topics": [domain] + [x.strip() for x in topics.replace("，", ",").split(",") if x.strip() and x.strip() not in DOMAINS],
                                "language": language, "rights_note": rights or "待人工确认"}
                    if title.strip():
                        metadata["title"] = title.strip()
                    if source.strip():
                        metadata["source_url"] = source.strip()
                    value = document_with_progress("/documents/jobs", files={"file": (file.name, file.getvalue(), "application/pdf")},
                                data={"metadata_json": json.dumps(metadata, ensure_ascii=False)})
                    if value:
                        st.session_state["upload_success"] = t('文献已加入馆藏：') + value["document"]["title"]
                        st.rerun()
                except ValueError:
                    st.error(t('年份须为整数或留空。'))
