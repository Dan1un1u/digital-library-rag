"""A/B/C 依赖注入及单进程互斥；不实现解析、排序或模型生成。"""
from __future__ import annotations

import importlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError
from dlrag.shared.config import Settings
from dlrag.shared.models import AnswerResponse, Chunk, Document, IndexManifest, RetrievalHit, error_answer


class ProjectError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def http_status(code):
    if code in {"NOT_FOUND", "FILE_NOT_FOUND"}:
        return 404
    if code == "UPLOAD_TOO_LARGE":
        return 413
    if code == "UNSUPPORTED_FILE":
        return 415
    if code in {"INVALID_REQUEST", "INVALID_PDF", "NO_EXTRACTABLE_TEXT", "FULLTEXT_REVIEW_REQUIRED", "TEXT_LAYER_REVIEW_REQUIRED",
                "CHUNK_CONFIG_MISMATCH", "UNSUPPORTED_HISTORY"}:
        return 422
    if code in {"INDEX_NOT_READY", "EMBEDDING_NOT_CONFIGURED", "EMBEDDING_MISMATCH",
                "MODEL_NOT_CONFIGURED", "MODEL_TIMEOUT", "MODEL_UNAVAILABLE",
                "EMBEDDING_UNAVAILABLE", "EMBEDDING_INVALID_RESPONSE",
                "TOKENIZER_NOT_CONFIGURED", "MODULE_NOT_AVAILABLE"}:
        return 503
    return 500


def boundary(model, value):
    try:
        return model.model_validate(value).model_dump()
    except ValidationError:
        # 不把上游输出/密钥放进错误正文；详细差异由联调测试定位。
        raise ProjectError("OUTPUT_VALIDATION_FAILED", f"模块返回不符合契约 1.0：{model.__name__}") from None


class Services:
    def __init__(self, settings, library=None, retriever=None, qa=None, issues=None,
                 embedding_configured=False, llm_configured=False):
        self.settings, self.library, self.retriever, self.qa = settings, library, retriever, qa
        self.issues = list(issues or [])
        self.embedding_configured, self.llm_configured = embedding_configured, llm_configured
        self.lock = threading.RLock()

    def require(self, name):
        value = getattr(self, name)
        if value is None:
            raise ProjectError("MODULE_NOT_AVAILABLE", f"{name} 模块尚未接入，请查看交接说明")
        return value

    def manifest(self):
        value = self.retriever.get_manifest() if self.retriever else None
        return boundary(IndexManifest, value) if value else None

    def health(self):
        with self.lock:
            manifest = self.manifest()
            ready = bool(self.library and self.retriever and self.qa and manifest
                         and self.embedding_configured and self.llm_configured)
            return {"status": "ready" if ready else "not_ready", "mode": self.settings.app_mode,
                    "embedding_configured": self.embedding_configured,
                    "llm_configured": self.llm_configured, "qa_available": self.qa is not None,
                    "index_version": manifest["index_version"] if manifest else None,
                    "manifest": manifest, "issues": self.issues,
                    "active_models": {"embedding": manifest["embedding_model"] if manifest else (
                        "fake-sha256-v1" if self.settings.app_mode == "mock" else self.settings.embedding_model),
                        "llm": "D-scripted-mock" if self.settings.app_mode == "mock" else self.settings.llm_model,
                        "semantic_reranker": getattr(getattr(self.qa, 'reranker', None), 'model', None),
                        "qa_engine": type(self.qa).__module__ + "." + type(self.qa).__name__ if self.qa else None},
                    "configuration": self.settings.public(),
                    "upload_notice": "上传入口仅适用于本地可信课堂环境；仅运行一个后端进程。",
                    "mock_notice": "模拟 embedding 与问答仅验证接口，不代表真实效果。"
                    if self.settings.app_mode == "mock" else None}

    def rebuild(self):
        with self.lock:
            store, retriever = self.require("library"), self.require("retriever")
            candidates = store.list_chunks(include_indexing=True)
            for chunk in candidates:
                boundary(Chunk, chunk)
            pending_ids = {c["doc_id"] for c in candidates}
            pending = [d for d in store.list_documents(include_nonready=True)
                       if d["doc_id"] in pending_ids and d["status"] == "indexing"]
            try:
                manifest = boundary(IndexManifest, retriever.build(candidates))
            except Exception as exc:
                info = {"code": getattr(exc, "code", "INDEX_BUILD_FAILED"),
                        "message": "索引重建失败；旧有效索引保持服务，请修复配置后重试。"}
                for doc in pending:
                    store.set_document_status(doc["doc_id"], "indexing", info)
                raise
            for doc in pending:
                store.set_document_status(doc["doc_id"], "ready")
            self.issues = [i for i in self.issues if i.get("component") != "index"]
            return manifest

    def ingest(self, path: str, metadata: dict, progress=None):
        if progress:
            progress("waiting")
        with self.lock:
            if progress:
                progress("document_parsing")
            store = self.require("library")
            doc = boundary(Document, store.ingest_pdf(path, metadata, self.settings.chunking_config.model_dump()))
            if doc["status"] == "failed":
                raise ProjectError(doc["error_code"] or "INVALID_PDF", doc["error_message"] or "解析失败")
            if doc["status"] not in ("indexing", "ready"):
                raise ProjectError("INDEX_NOT_READY", "文献尚未完成解析")
            # 同一文件已 ready 且有效索引存在时，无需再次全量构建。
            manifest = self.manifest()
            if doc["status"] != "ready" or not manifest:
                if progress:
                    progress("document_processing")
                manifest = self.rebuild()
            if progress:
                progress("document_saving")
            return {"document": boundary(Document, store.get_document(doc["doc_id"])),
                    "index_version": manifest["index_version"]}

    def search(self, request):
        with self.lock:
            retriever = self.require("retriever")
            manifest = self.manifest()
            if not manifest:
                raise ProjectError("INDEX_NOT_READY", "请先导入文献并建立索引")
            raw = retriever.search(**request.model_dump())
            hits = [boundary(RetrievalHit, hit) for hit in raw]
            if any(h["index_version"] != manifest["index_version"] or h["rank"] != i
                   for i, h in enumerate(hits, 1)):
                raise ProjectError("OUTPUT_VALIDATION_FAILED", "检索排名或索引版本不一致")
            documents, seen = [], set()
            for hit in hits:
                chunk = hit["chunk"]
                if chunk["doc_id"] not in seen:
                    seen.add(chunk["doc_id"])
                    doc = chunk["document"]
                    documents.append({"doc_id": chunk["doc_id"], "title": doc["title"],
                                      "authors": doc["authors"], "year": doc["year"],
                                      "best_rank": hit["rank"], "preview": chunk["text"][:300]})
            return {"hits": hits, "documents": documents, "index_version": manifest["index_version"]}

    def ask(self, request, progress=None):
        if progress:
            progress("waiting")
        with self.lock:
            if request.history:
                return error_answer(request.question, "UNSUPPORTED_HISTORY", "第一版仅支持独立单轮提问，history 必须为空。")
            if self.settings.app_mode == "real" and not self.llm_configured:
                return error_answer(request.question, "MODEL_NOT_CONFIGURED", "请配置 C 的模型服务和客户端工厂。")
            qa = self.require("qa")
            before = self.manifest()
            if progress and callable(getattr(qa, "ask_with_progress", None)):
                raw = qa.ask_with_progress(request.model_dump(), progress)
            else:
                if progress:
                    progress("generation")
                raw = qa.ask(request.model_dump())
            answer = boundary(AnswerResponse, raw)
            if answer["index_version"] is not None and (not before or answer["index_version"] != before["index_version"]):
                raise ProjectError("OUTPUT_VALIDATION_FAILED", "问答证据没有固定在同一索引版本")
            return answer

    def file_path(self, doc_id):
        with self.lock:
            store = self.require("library")
            if not store.get_document(doc_id):
                raise ProjectError("NOT_FOUND", "文献不存在")
            value = store.get_file_path(doc_id)
            if not value:
                raise ProjectError("NOT_FOUND", "原文件不存在")
            path = Path(value).resolve()
            if not path.is_relative_to(self.settings.files_dir) or not path.is_file():
                raise ProjectError("NOT_FOUND", "原文件不可用")
            return path

    def feedback(self, feedback):
        with self.lock:
            self.settings.data_dir.mkdir(parents=True, exist_ok=True)
            row = {**feedback.model_dump(), "created_at": datetime.now(timezone.utc).isoformat()}
            with (self.settings.data_dir / "feedback.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            return {"saved": True}


def assemble(settings: Settings) -> Services:
    """构造一次并重用。缺模块可启动健康检查，真实模式从不回退 mock。"""
    service = Services(settings)
    try:
        from dlrag.ingestion.library import LibraryStore
        from dlrag.ingestion.chunker import normalize_config
        service.library = LibraryStore(str(settings.db_path), str(settings.files_dir))
        actual_chunking = normalize_config(settings.chunking_config.model_dump())
    except ImportError:
        service.issues.append({"component": "A", "code": "MODULE_NOT_AVAILABLE", "message": "缺少 A 的 LibraryStore"})
        actual_chunking = settings.chunking_config.model_dump()
    except Exception as exc:
        service.issues.append({"component": "A", "code": getattr(exc, "code", "INTERNAL_ERROR"), "message": "馆藏或切块配置未就绪"})
        actual_chunking = settings.chunking_config.model_dump()
    try:
        from dlrag.retrieval.retriever import Retriever
        from dlrag.retrieval.embeddings import FakeHashEmbedding, SiliconFlowEmbedding
        if settings.app_mode == "mock":
            backend = FakeHashEmbedding()
            service.embedding_configured = True
        else:
            if settings.embedding_revision:
                raise ProjectError("EMBEDDING_MISMATCH", "当前硅基流动适配器没有可固定修订，请留空 EMBEDDING_REVISION")
            key = settings.siliconflow_api_key.get_secret_value() or settings.sd_embedding_key.get_secret_value()
            backend = SiliconFlowEmbedding(api_key=key, model=settings.embedding_model,
                                           dimension=settings.embedding_dimension,
                                           base_url=settings.siliconflow_base_url)
            service.embedding_configured = bool(key)
        service.retriever = Retriever(str(settings.index_dir), backend,
                                     {"candidate_k": 20, "rrf_k": 60, "normalize_embeddings": True,
                                      "chunking_config": actual_chunking})
        try:
            service.retriever.load()
        except Exception as exc:
            service.issues.append({"component": "index", "code": getattr(exc, "code", "INDEX_NOT_READY"),
                                   "message": "没有可加载的兼容索引，请检查配置或运行重建。"})
    except ImportError:
        service.issues.append({"component": "B", "code": "MODULE_NOT_AVAILABLE", "message": "缺少 B 的 Retriever 或依赖"})
    except Exception as exc:
        service.issues.append({"component": "B", "code": getattr(exc, "code", "INTERNAL_ERROR"), "message": "检索器配置未就绪"})
    if settings.app_mode == "mock":
        from .mock_qa import ScriptedQA
        service.qa = ScriptedQA(service.retriever)
        service.llm_configured = True
    else:
        has_key = bool(settings.llm_api_key.get_secret_value() or settings.siliconflow_api_key.get_secret_value())
        configured = bool(settings.llm_base_url and settings.llm_model and has_key and settings.llm_client_factory)
        if not configured:
            service.issues.append({"component": "C", "code": "MODEL_NOT_CONFIGURED",
                                   "message": "缺少 LLM_BASE_URL / LLM_MODEL / LLM_API_KEY / LLM_CLIENT_FACTORY"})
        try:
            from dlrag.qa.engine import QAEngine
            if configured:
                module, name = settings.llm_client_factory.split(":", 1)
                factory = getattr(importlib.import_module(module), name)
                client = factory(settings)
                from dlrag.qa.semantic_reranker import SiliconFlowReranker
                reranker = SiliconFlowReranker(
                    api_key=settings.siliconflow_api_key.get_secret_value(), model=settings.qa_rerank_model,
                    base_url=settings.siliconflow_base_url, timeout=settings.qa_rerank_timeout_seconds
                ) if settings.qa_semantic_rerank_enabled else None
                service.qa = QAEngine(service.retriever, client, {
                    "planning_enabled": settings.planning_enabled, "retrieval_mode": settings.retrieval_mode,
                    "sentence_citations_required": True,
                    "retrieval_top_k": 20, "max_evidence_chunks": settings.qa_max_evidence_chunks,
                    "context_budget_tokens": settings.qa_context_budget_tokens,
                    "bilingual_retrieval_enabled": settings.qa_bilingual_retrieval_enabled,
                    "evidence_rerank_enabled": settings.qa_evidence_rerank_enabled,
                    "reference_penalty_enabled": settings.qa_reference_penalty_enabled,
                    "neighbor_expansion_enabled": settings.qa_neighbor_expansion_enabled,
                    "neighbor_radius": settings.qa_neighbor_radius, "neighbor_seed_k": settings.qa_neighbor_seed_k,
                    "max_output_tokens": getattr(client, "max_output_tokens", 1000), "max_answer_repairs": 1,
                    "context_window_tokens": getattr(client, "context_window_tokens", 32768),
                }, reranker=reranker)
                service.llm_configured = True
        except ImportError:
            service.issues.append({"component": "C", "code": "MODULE_NOT_AVAILABLE", "message": "缺少 C 的 QAEngine 或客户端"})
        except Exception as exc:
            service.issues.append({"component": "C", "code": getattr(exc, "code", "MODEL_NOT_CONFIGURED"),
                                   "message": "C 客户端工厂配置失败：" + (getattr(exc, "message", None) or type(exc).__name__)})
    return service
