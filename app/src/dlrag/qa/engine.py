"""Contract 1.0 single-turn QA orchestration with at most three model calls."""
import copy
import time
import uuid
import re
from pathlib import Path

from .errors import ProjectError
from .evidence import payload_for, public_answer, related_documents, select_evidence, validate_hits, restore_references
from .llm_client import input_upper_bound
from .planner import original_plan, validate_plan
from .validation import validate_answer, validate_request
from .retrieval import fuse_queries
from .reranking import rerank, expand_neighbors

DEFAULTS = dict(planning_enabled=True, retrieval_mode="hybrid", retrieval_top_k=20,
                max_evidence_chunks=8, context_budget_tokens=18000, max_output_tokens=1000,
                max_answer_repairs=1, context_window_tokens=32768,
                bilingual_retrieval_enabled=True, evidence_rerank_enabled=True,
                reference_penalty_enabled=True, neighbor_expansion_enabled=True,
                neighbor_radius=1, neighbor_seed_k=3, sentence_citations_required=False,
                corpus_scope="数字图书馆、信息检索与知识组织主题馆藏；具体资料以检索证据为准")


def prompt(name):
    return (Path(__file__).parent / "prompts" / (name + ".txt")).read_text(encoding="utf-8")


class QAEngine:
    def __init__(self, retriever, llm_client, settings: dict, reranker=None):
        if not isinstance(settings, dict) or set(settings) - set(DEFAULTS):
            raise ProjectError("INVALID_REQUEST", "未知 QA 配置")
        self.settings = {**DEFAULTS, **settings}
        s = self.settings
        for key in ("retrieval_top_k", "max_evidence_chunks", "context_budget_tokens", "max_output_tokens", "context_window_tokens"):
            if type(s[key]) is not int or s[key] < 1:
                raise ProjectError("INVALID_REQUEST", "QA 数字配置必须为正整数")
        if (type(s["planning_enabled"]) is not bool or type(s["max_answer_repairs"]) is not int
                or s["max_answer_repairs"] not in (0, 1) or s["retrieval_mode"] not in {"keyword", "vector", "hybrid"}
                or not 1 <= s["retrieval_top_k"] <= 50 or not 1 <= s["max_evidence_chunks"] <= 12
                or not isinstance(s["corpus_scope"], str)):
            raise ProjectError("INVALID_REQUEST", "QA 配置超出支持范围")
        for key in ("bilingual_retrieval_enabled", "evidence_rerank_enabled", "reference_penalty_enabled", "neighbor_expansion_enabled", "sentence_citations_required"):
            if type(s[key]) is not bool:
                raise ProjectError("INVALID_REQUEST", "QA 开关必须为布尔值")
        if (type(s["neighbor_radius"]) is not int or not 1 <= s["neighbor_radius"] <= 2
                or type(s["neighbor_seed_k"]) is not int or not 1 <= s["neighbor_seed_k"] <= 5):
            raise ProjectError("INVALID_REQUEST", "相邻片段扩展参数超出支持范围")
        # A client with a smaller limit always wins. Never override its declared limit.
        s["context_window_tokens"] = min(s["context_window_tokens"], getattr(llm_client, "context_window_tokens", s["context_window_tokens"]))
        if getattr(llm_client, "max_output_tokens", s["max_output_tokens"]) != s["max_output_tokens"]:
            raise ProjectError("INVALID_REQUEST", "QA 与 LLM 输出预算必须一致")
        if s["context_window_tokens"] <= s["max_output_tokens"]:
            raise ProjectError("INVALID_REQUEST", "输出预算超过上下文上限")
        self.retriever, self.llm = retriever, llm_client
        self.reranker = reranker
        self.planning_prompt = prompt("query_planning")
        self.answer_prompt = prompt("grounded_answer")
        self.repair_prompt = self.answer_prompt + "\n" + prompt("repair_answer")

    def ask_with_progress(self, request, progress):
        return self.ask(request, progress)

    def ask(self, request: dict, progress=None) -> dict:
        def notify(stage):
            if progress:
                try:
                    progress(stage)
                except Exception:
                    pass  # A disconnected progress observer must not corrupt the answer.
        started = time.perf_counter()
        rerank_records = getattr(getattr(self.reranker, 'client', None), 'records', [])
        rerank_calls_before = len(rerank_records)
        r = dict(request_id="q_" + uuid.uuid4().hex, status="error", query_plan=original_plan(""),
                 claims=[], evidence=[], related_documents=[], limitations=[], clarification_question=None,
                 clarification_options=[], index_version=None,
                 timings_ms=dict(planning=0, retrieval=0, generation=0, total=0), error=None,
                 diagnostics=dict(planning_enabled=self.settings["planning_enabled"], multi_query=False,
                                  model_calls=0, retrieval_calls=0, selected_chunk_ids=[], selected_evidence=[],
                                  planning_fallback=None, retrieval_fallback=False,
                                  modification_version="v1.0", retrieval_queries=[], neighbor_lookups=0,
                                  rerank_method="local_body_bm25_and_rank_prior_v1", reranked_candidates=[],
                                  budget_count_mode="utf8_byte_upper_bound"))
        diag, s = r["diagnostics"], self.settings

        def generate(system, payload):
            if input_upper_bound(system, payload) + s["max_output_tokens"] > s["context_window_tokens"]:
                raise ProjectError("INVALID_REQUEST", "问题和提示超出模型上下文预算")
            diag["model_calls"] += 1
            return self.llm.generate_json(system, copy.deepcopy(payload))

        def timed(stage, operation):
            t = time.perf_counter()
            try:
                return operation()
            finally:
                r["timings_ms"][stage] = r["timings_ms"].get(stage, 0) + round((time.perf_counter() - t) * 1000, 3)

        def search(query, filters):
            diag["retrieval_calls"] += 1
            started_query = time.perf_counter()
            entry = dict(query=query, mode=s["retrieval_mode"], hit_count=0, keyword_hits=0, vector_hits=0)
            diag["retrieval_queries"].append(entry)
            try:
                hits = self.retriever.search(query, filters=copy.deepcopy(filters), mode=s["retrieval_mode"], top_k=s["retrieval_top_k"])
                entry.update(hit_count=len(hits), keyword_hits=sum("keyword" in h.get("matched_by", []) for h in hits),
                             vector_hits=sum("vector" in h.get("matched_by", []) for h in hits))
                return hits
            finally:
                entry["elapsed_ms"] = round((time.perf_counter() - started_query) * 1000, 3)

        try:
            question, filters = validate_request(request)
            r["query_plan"] = original_plan(question)
            if s["planning_enabled"]:
                notify("planning")
                def plan():
                    try:
                        value = generate(self.planning_prompt, {"question": question, "corpus_scope": s["corpus_scope"],
                                                               "bilingual_retrieval_enabled": s["bilingual_retrieval_enabled"]})
                        return validate_plan(value, question)
                    except ProjectError as e:
                        if e.code not in {"OUTPUT_VALIDATION_FAILED", "MODEL_TIMEOUT", "MODEL_UNAVAILABLE"}:
                            raise
                        diag["planning_fallback"] = e.code
                        r["limitations"].append("查询规划失败，已回退原问题：" + e.code)
                        return original_plan(question)
                r["query_plan"] = timed("planning", plan)
            plan = r["query_plan"]
            if plan["needs_clarification"]:
                r.update(status="needs_clarification", clarification_question=plan["clarification_question"],
                         clarification_options=plan["clarification_options"])
                return r

            def retrieve():
                query = plan["rewritten_query"]
                if (s["bilingual_retrieval_enabled"] and plan.get("english_query")
                        and re.search(r"[\u3400-\u9fff]", question) and not re.search(r"[\u3400-\u9fff]", query)):
                    query = question
                    diag["original_language_query_fallback"] = True
                try:
                    primary = search(query, filters)
                except Exception as e:
                    # Only a query-specific parameter rejection can benefit from original-query retry.
                    if query == question or getattr(e, "code", None) != "INVALID_REQUEST":
                        raise
                    primary = []
                groups = [primary]
                english = plan.get("english_query")
                if (s["planning_enabled"] and s["bilingual_retrieval_enabled"] and english
                        and re.search(r"[\u3400-\u9fff]", question) and english.casefold() != query.casefold()):
                    diag["multi_query"] = True
                    try:
                        groups.append(search(english, filters))
                    except Exception as e:
                        code = getattr(e, "code", None)
                        if code not in {"INVALID_REQUEST", "EMBEDDING_UNAVAILABLE"}:
                            raise
                        diag["secondary_query_error"] = code
                        r["limitations"].append("英文检索分支失败，保留原语言检索结果：" + code)
                        if not primary:
                            raise
                mechanism = plan.get('mechanism_query')
                used_queries = {entry['query'].casefold() for entry in diag['retrieval_queries']}
                if (s['planning_enabled'] and mechanism and mechanism.casefold() not in used_queries
                        and (s['bilingual_retrieval_enabled'] or not re.search(r'[\u3400-\u9fff]', question))):
                    diag['multi_query'] = True
                    try:
                        groups.append(search(mechanism, filters))
                    except Exception as e:
                        if getattr(e, 'code', None) not in {'INVALID_REQUEST','EMBEDDING_UNAVAILABLE'}:
                            raise
                        diag['mechanism_query_error'] = getattr(e,'code')
                        r['limitations'].append('机制补充检索暂不可用，保留已有检索结果。')
                hits = fuse_queries(groups)
                if not hits and query != question:
                    diag["retrieval_fallback"] = True
                    r["limitations"].append("改写查询未获得结果，已使用原问题回退检索")
                    hits = search(question, filters)
                return copy.deepcopy(hits)
            notify("retrieval")
            hits = timed("retrieval", retrieve)
            diag['retrieved_unique_chunks'] = len(hits)
            version = validate_hits(hits)
            if version is None:
                manifest = self.retriever.get_manifest()
                version = manifest.get("index_version") if isinstance(manifest, dict) else None
            r["index_version"] = version
            def choose():
                ranked = rerank(hits, question, plan, s) if s["evidence_rerank_enabled"] else hits
                expanded, lookups = expand_neighbors(self.retriever, ranked, filters, version, s)
                if validate_hits(expanded) not in (None, version):
                    raise ProjectError("INDEX_NOT_READY", "扩展证据与检索版本不一致")
                diag["neighbor_lookups"] = lookups
                if s["evidence_rerank_enabled"]:
                    expanded = rerank(expanded, question, plan, s)
                    if self.reranker:
                        try:
                            from .semantic_reranker import rank_question_and_mechanism
                            rerank_query = question + '\n' + (plan.get('english_query') or plan['rewritten_query'])
                            expanded = rank_question_and_mechanism(self.reranker,rerank_query,plan.get('mechanism_query'),expanded)
                            diag['semantic_rerank_queries'] = 2 if plan.get('mechanism_query') else 1
                            diag['rerank_method'] = getattr(self.reranker, 'method', 'semantic_cross_encoder') + ':' + self.reranker.model
                            diag['semantic_rerank_status'] = 'ok'
                        except ProjectError:
                            diag['semantic_rerank_status'] = 'fallback_local'
                            r['limitations'].append('语义重排暂不可用，本次使用本地排序；结果相关性可能下降。')
                diag["reranked_candidates"] = [dict(chunk_id=h["chunk"]["chunk_id"], doc_id=h["chunk"]["doc_id"],
                    pdf_page=h["chunk"]["pdf_page"], **h.get("local_rerank", {})) for h in expanded]
                return select_evidence(expanded, question, plan, s, [self.answer_prompt, self.repair_prompt])
            notify("evidence_selection")
            selected = timed("evidence_selection", choose)
            diag["selected_chunk_ids"] = [c["chunk_id"] for c in selected]
            # Preserve the exact generation context for evaluation, including
            # candidate evidence that the final answer did not cite.
            diag["selected_evidence"] = copy.deepcopy(selected)
            r["related_documents"] = related_documents(selected)
            if not selected:
                r["status"] = "insufficient_evidence"
                r["limitations"].append("未检索到证据" if not hits else "上下文预算内没有可完整提供的证据片段")
                return r
            payload = payload_for(question, plan, selected)
            if self.reranker:
                payload['citation_mode'] = 'server_sentence_grounding'
                payload['answer_format'] = 'simple'
                for entry, chunk in zip(payload['evidence'],selected):
                    entry['text'] = chunk['text']
            diag["input_budget_upper_bound"] = max(input_upper_bound(system, {**payload,
                "validation_error": "验" * 100}) for system in [self.answer_prompt, self.repair_prompt])
            diag["context_budget_upper_bound_limit"] = s["context_budget_tokens"]
            diag["context_window_tokens"] = s["context_window_tokens"]

            def answer():
                validation_error = '引用或结构校验失败，请重新生成'
                for attempt in range(s["max_answer_repairs"] + 1):
                    try:
                        notify("generation" if attempt == 0 else "repair")
                        system = self.answer_prompt if attempt == 0 else self.repair_prompt
                        current = payload if attempt == 0 else {**payload, "validation_error": validation_error}
                        generated = generate(system, current)
                        notify("validation")
                        normalized = restore_references(generated, selected)
                        if self.reranker and isinstance(normalized,dict) and isinstance(normalized.get('claims'),list):
                            normalized.pop('sections',None)
                            normalized.pop('coverage',None)
                            for claim in normalized['claims']:
                                if isinstance(claim,dict):
                                    claim.pop('evidence_sentences',None)
                        validated = validate_answer(normalized, selected, require_sentence_refs=s["sentence_citations_required"] and not self.reranker)
                        from .coverage import validate_coverage
                        if not self.reranker:
                            validate_coverage(validated, plan.get('answer_requirements', []))
                        return validated
                    except ProjectError as e:
                        if e.code != "OUTPUT_VALIDATION_FAILED" or attempt == s["max_answer_repairs"]:
                            raise
                        diag.setdefault('validation_failures', []).append(e.message)
                        # Validator messages are fixed local descriptions, never provider bodies.
                        validation_error = e.message[:100]
                raise AssertionError("unreachable")
            value = timed("generation", answer)
            if value['status']=='answered' and self.reranker:
                notify('citation_grounding')
                try:
                    from .grounding import ground_sentences
                    value = timed('citation_grounding',lambda:ground_sentences(value,selected,self.reranker))
                    notify('validation')
                    validate_answer(value,selected,require_sentence_refs=True)
                    diag['sentence_grounding_status'] = 'ok'
                except ProjectError:
                    diag['sentence_grounding_status'] = 'unavailable'
                    for claim in value['claims']:
                        claim.pop('evidence_sentences',None)
                    r['limitations'].append('句子定位服务暂不可用，本次保留片段引用，可打开原文核对。')
                if plan.get('answer_requirements'):
                    notify('coverage_check')
                    try:
                        from .coverage import map_coverage
                        value['coverage'] = timed('coverage_check',lambda:map_coverage(value,plan['answer_requirements'],self.reranker))
                        diag['coverage_check_status'] = 'ok'
                    except ProjectError:
                        value['coverage'] = []
                        diag['coverage_check_status'] = 'unavailable'
                        r['limitations'].append('问题要点的自动关联检查暂不可用，请结合原文核对回答范围。')
            r["status"] = value["status"]
            r["limitations"].extend(value["limitations"])
            if value["status"] == "answered":
                r["claims"], r["evidence"] = public_answer(value, selected)
                sections = value.get('sections')
                if sections is None:
                    sections, group, size = [], [], 0
                    for i,claim in enumerate(r['claims'],1):
                        if group and size + len(claim['text']) > 320:
                            sections.append({'heading':'','claim_indices':group})
                            group, size = [], 0
                        group.append(i)
                        size += len(claim['text'])
                    if group:
                        sections.append({'heading':'','claim_indices':group})
                r["answer_sections"] = [{"heading": section["heading"],
                    "claim_ids": [r["claims"][i - 1]["claim_id"] for i in section["claim_indices"]]} for section in sections]
                r['coverage'] = value.get('coverage', [])
                for row in r['coverage']:
                    if row['gap'].strip() and row['gap'] not in r['limitations']:
                        r['limitations'].append(row['gap'])
            return r
        except Exception as e:
            safe = {
                "INVALID_REQUEST": "请求或配置非法", "UNSUPPORTED_HISTORY": "第一版只支持单轮请求",
                "MODEL_NOT_CONFIGURED": "生成模型未配置或鉴权失败", "MODEL_TIMEOUT": "生成模型请求超时",
                "MODEL_UNAVAILABLE": "生成模型服务不可用", "OUTPUT_VALIDATION_FAILED": "生成输出在有限修复后仍不合规",
                "INDEX_NOT_READY": "索引或引用片段未就绪", "EMBEDDING_NOT_CONFIGURED": "嵌入模型未配置",
                "EMBEDDING_MISMATCH": "嵌入配置与索引不兼容", "EMBEDDING_UNAVAILABLE": "嵌入服务不可用",
                "EMBEDDING_INVALID_RESPONSE": "嵌入服务响应非法"}
            code = getattr(e, "code", "INTERNAL_ERROR")
            if code not in safe:
                code = "INTERNAL_ERROR"
            r.update(status="error", claims=[], evidence=[], error={"code": code, "message": safe.get(code, "问答处理失败")})
            return r
        finally:
            diag['rerank_model_calls'] = len(rerank_records) - rerank_calls_before
            diag['retrieved_unique_chunks'] = diag.get('retrieved_unique_chunks', 0)
            diag['candidate_chunks'] = len(diag['reranked_candidates'])
            diag['selected_chunks'] = len(diag['selected_chunk_ids'])
            diag['cited_chunks'] = len(r['evidence'])
            r["timings_ms"]["total"] = round((time.perf_counter() - started) * 1000, 3)
