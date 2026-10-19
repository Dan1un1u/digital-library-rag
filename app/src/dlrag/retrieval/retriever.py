"""统一检索接口与原子切换的完整索引快照。"""

import copy
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .errors import ProjectError
from .fusion import reciprocal_rank_fusion
from .lexical import BM25, TOKENIZER_VERSION, tokenize

DEFAULTS = {"candidate_k": 20, "rrf_k": 60, "normalize_embeddings": True,
            "bm25_k1": 1.5, "bm25_b": 0.75, "chunking_config": None}
CHUNK_KEYS = {"chunk_id", "doc_id", "pdf_page", "printed_page", "section", "text",
              "page_char_start", "page_char_end", "token_count", "document"}
DOC_KEYS = {"title", "authors", "year", "topics", "language"}
CHUNKING_KEYS = {"count_mode", "tokenizer_name", "tokenizer_revision", "max_tokens",
                 "overlap_tokens", "max_chars", "overlap_chars"}
VECTOR_TEXT_POLICY = "document-title-prefix-v1"


def vector_text(chunk):
    """Add retrieval context without changing the quoted body or page offsets."""
    return "Title: " + chunk["document"]["title"] + "\n\n" + chunk["text"]


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest_file(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    with path.open("w", encoding="utf-8") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def validate_filters(filters):
    if filters is None:
        filters = {}
    if not isinstance(filters, dict) or set(filters) - {"year_from", "year_to", "topics"}:
        raise ProjectError("INVALID_REQUEST", "只接受 year_from/year_to/topics 过滤条件")
    low, high = filters.get("year_from"), filters.get("year_to")
    for value in (low, high):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
            raise ProjectError("INVALID_REQUEST", "年份边界必须是整数或 null")
    if low is not None and high is not None and low > high:
        raise ProjectError("INVALID_REQUEST", "年份下界不能大于上界")
    topics = filters.get("topics", [])
    if not isinstance(topics, list) or any(not isinstance(t, str) or not t.strip() for t in topics):
        raise ProjectError("INVALID_REQUEST", "主题必须是非空字符串组成的列表")
    return low, high, set(topics)


def validate_chunks(chunks):
    if not isinstance(chunks, list):
        raise ProjectError("INVALID_REQUEST", "文本块必须是列表")
    try:
        result = json.loads(canonical(chunks))
    except (TypeError, ValueError):
        raise ProjectError("INVALID_REQUEST", "文本块必须能序列化为合法 JSON") from None
    ids, documents = set(), {}
    for chunk in result:
        if not isinstance(chunk, dict) or not CHUNK_KEYS <= chunk.keys():
            raise ProjectError("INVALID_REQUEST", "文本块缺少共同契约字段")
        if any(not isinstance(chunk[k], str) or not chunk[k].strip() for k in ("chunk_id", "doc_id", "text")):
            raise ProjectError("INVALID_REQUEST", "文本块标识和正文必须是非空字符串")
        if chunk["chunk_id"] in ids:
            raise ProjectError("INVALID_REQUEST", "文本块编号重复")
        ids.add(chunk["chunk_id"])
        page, start, end = (chunk[k] for k in ("pdf_page", "page_char_start", "page_char_end"))
        if (any(isinstance(x, bool) or not isinstance(x, int) for x in (page, start, end))
                or page < 1 or start < 0 or end <= start or end - start != len(chunk["text"])):
            raise ProjectError("INVALID_REQUEST", "页序号或页内偏移不符合契约")
        token_count = chunk["token_count"]
        if token_count is not None and (isinstance(token_count, bool) or not isinstance(token_count, int) or token_count < 1):
            raise ProjectError("INVALID_REQUEST", "词元数必须为正整数或 null")
        for name in ("printed_page", "section"):
            if chunk[name] is not None and not isinstance(chunk[name], str):
                raise ProjectError("INVALID_REQUEST", "印刷页码和章节必须为字符串或 null")
        doc = chunk["document"]
        if not isinstance(doc, dict) or not DOC_KEYS <= doc.keys():
            raise ProjectError("INVALID_REQUEST", "文献快照缺少共同契约字段")
        if not isinstance(doc["title"], str) or not doc["title"].strip():
            raise ProjectError("INVALID_REQUEST", "文献标题不能为空")
        for field in ("authors", "topics"):
            if not isinstance(doc[field], list) or any(not isinstance(v, str) or not v.strip() for v in doc[field]):
                raise ProjectError("INVALID_REQUEST", "作者和主题必须是字符串列表")
        if doc["year"] is not None and (isinstance(doc["year"], bool) or not isinstance(doc["year"], int)):
            raise ProjectError("INVALID_REQUEST", "文献年份必须为整数或 null")
        if doc["language"] not in ("zh", "en", "mixed", "unknown"):
            raise ProjectError("INVALID_REQUEST", "文献语言不符合契约")
        if chunk["doc_id"] in documents and documents[chunk["doc_id"]] != doc:
            raise ProjectError("INVALID_REQUEST", "同一文献的元数据快照不一致")
        documents[chunk["doc_id"]] = doc
    return sorted(result, key=lambda c: c["chunk_id"])


def normalize_chunking(config, chunks):
    if config is None:
        if chunks:
            raise ProjectError("INVALID_REQUEST", "建索引须提供 A 返回的完整 Document.chunking_config")
        return None
    if not isinstance(config, dict) or set(config) != CHUNKING_KEYS:
        raise ProjectError("INVALID_REQUEST", "切块配置须包含共同契约的全部字段")
    config = json.loads(canonical(config))
    if config["count_mode"] not in ("character", "token"):
        raise ProjectError("INVALID_REQUEST", "计数模式必须为 character 或 token")
    for key in ("max_tokens", "overlap_tokens", "max_chars", "overlap_chars"):
        if isinstance(config[key], bool) or not isinstance(config[key], int) or config[key] < 0:
            raise ProjectError("INVALID_REQUEST", "切块长度和重叠必须为非负整数")
    token_mode = config["count_mode"] == "token"
    maximum = config["max_tokens"] if token_mode else config["max_chars"]
    overlap = config["overlap_tokens"] if token_mode else config["overlap_chars"]
    if maximum < 1 or overlap >= maximum:
        raise ProjectError("INVALID_REQUEST", "必须满足 0 ≤ 重叠 < 块长")
    if token_mode:
        if not isinstance(config["tokenizer_name"], str) or not config["tokenizer_name"]:
            raise ProjectError("INVALID_REQUEST", "词元模式须记录实际分词器名称")
        if config["tokenizer_revision"] is not None and not isinstance(config["tokenizer_revision"], str):
            raise ProjectError("INVALID_REQUEST", "分词器修订必须为字符串或 null")
    elif config["tokenizer_name"] is not None or config["tokenizer_revision"] is not None:
        raise ProjectError("INVALID_REQUEST", "字符模式的分词器名称和修订须为 null")
    for chunk in chunks:
        count = chunk["token_count"] if token_mode else len(chunk["text"])
        if (token_mode and count is None) or (not token_mode and chunk["token_count"] is not None) or count > maximum:
            raise ProjectError("INVALID_REQUEST", "文本块计数与声明的切块配置不一致")
    return config


class Retriever:
    def __init__(self, index_dir: str, embedding_backend, settings: dict):
        if not isinstance(settings, dict) or set(settings) - set(DEFAULTS):
            raise ProjectError("INVALID_REQUEST", "检索配置包含未知字段")
        self.settings = {**DEFAULTS, **copy.deepcopy(settings)}
        for key in ("candidate_k", "rrf_k"):
            value = self.settings[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ProjectError("INVALID_REQUEST", "候选数和融合常数必须为正整数")
        if not isinstance(self.settings["normalize_embeddings"], bool):
            raise ProjectError("INVALID_REQUEST", "归一化配置必须为布尔值")
        for key, low, high in (("bm25_k1", 0, float("inf")), ("bm25_b", 0, 1)):
            value = self.settings[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high or (key == "bm25_k1" and value == 0):
                raise ProjectError("INVALID_REQUEST", "BM25 参数不合法")
        self.index_dir = Path(index_dir).resolve()
        self.backend = embedding_backend
        self._snapshot = None
        self._lock = threading.RLock()

    def _backend_config(self):
        if self.backend is None:
            raise ProjectError("EMBEDDING_NOT_CONFIGURED", "构建或加载索引须注入嵌入适配器")
        method = getattr(self.backend, "get_config", None)
        if callable(method):
            config = method()
            allowed = {"provider", "model", "revision", "dimension", "base_url", "encoding_format",
                       "input_preprocessing", "revision_pinned"}
            if not isinstance(config, dict) or set(config) - allowed:
                raise ProjectError("INVALID_REQUEST", "嵌入配置只接受公开模型身份字段")
            config = json.loads(canonical(config))
        else:
            config = {"provider": "injected", "model": getattr(self.backend, "model", type(self.backend).__name__),
                      "revision": getattr(self.backend, "revision", None),
                      "dimension": getattr(self.backend, "dimension", None)}
        if not isinstance(config.get("model"), str) or not config["model"]:
            raise ProjectError("INVALID_REQUEST", "嵌入适配器须提供模型名称")
        return config

    def _encode(self, texts, dimension=None):
        try:
            vectors = np.asarray(self.backend.encode(texts), dtype=np.float32)
            if vectors.ndim != 2 or vectors.shape[0] != len(texts) or vectors.shape[1] < 1:
                raise ValueError("嵌入矩阵形状不正确")
            if dimension is not None and vectors.shape[1] != dimension:
                raise ProjectError("EMBEDDING_MISMATCH", "嵌入维度与索引不一致")
            if not np.isfinite(vectors).all():
                raise ValueError("嵌入矩阵包含非有限值")
            norms = np.linalg.norm(vectors.astype(np.float64), axis=1)
            if np.any(norms == 0):
                raise ValueError("嵌入矩阵包含零向量")
            if self.settings["normalize_embeddings"]:
                vectors = (vectors / norms[:, None]).astype(np.float32)
            return vectors
        except ProjectError:
            raise
        except Exception:
            raise ProjectError("EMBEDDING_INVALID_RESPONSE", "嵌入计算失败或向量数值不合法") from None

    def _retrieval_config(self):
        return {**{key: self.settings[key] for key in ("candidate_k", "rrf_k", "normalize_embeddings", "bm25_k1", "bm25_b")},
                "vector_text_policy": VECTOR_TEXT_POLICY}

    def build(self, chunks: list[dict]) -> dict:
        with self._lock:
            chunks = validate_chunks(chunks)
            chunking = normalize_chunking(self.settings["chunking_config"], chunks)
            backend_config = self._backend_config()
            try:
                self.index_dir.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix=".building_", dir=self.index_dir))
            except OSError:
                raise ProjectError("INDEX_BUILD_FAILED", "无法创建新索引目录，原索引保持可用") from None
            try:
                dimension = backend_config.get("dimension")
                if chunks:
                    vectors = self._encode([vector_text(c) for c in chunks], dimension)
                    dimension = vectors.shape[1]
                else:
                    if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 1:
                        raise ProjectError("EMBEDDING_NOT_CONFIGURED", "空馆藏须由适配器明确向量维度")
                    vectors = np.empty((0, dimension), dtype=np.float32)
                token_lists = [tokenize("\n".join([c["document"]["title"], *c["document"]["topics"], c["text"]])) for c in chunks]
                lexical = BM25(token_lists, self.settings["bm25_k1"], self.settings["bm25_b"])
                stamp = datetime.now(timezone.utc)
                version = "idx_" + stamp.strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:12]
                write_json(stage / "chunks.json", chunks)
                write_json(stage / "lexical.json", {"tokenizer": TOKENIZER_VERSION, "tokens": token_lists})
                with (stage / "vectors.npy").open("wb") as stream:
                    np.save(stream, vectors, allow_pickle=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                manifest = {
                    "index_version": version, "contract_version": "1.0", "built_at": stamp.isoformat(),
                    "embedding_model": backend_config["model"], "embedding_revision": backend_config.get("revision"),
                    "dimension": dimension, "normalized": self.settings["normalize_embeddings"],
                    "embedding_backend": backend_config, "chunking_config": chunking,
                    "tokenizer": None if chunking is None or chunking["count_mode"] == "character" else {
                        "name": chunking["tokenizer_name"], "revision": chunking["tokenizer_revision"]},
                    "lexical_tokenizer": TOKENIZER_VERSION, "retrieval_config": self._retrieval_config(),
                    "document_count": len({c["doc_id"] for c in chunks}), "chunk_count": len(chunks),
                    "corpus_hash": hashlib.sha256(canonical(chunks).encode("utf-8")).hexdigest(),
                    "artifacts": {name: digest_file(stage / name) for name in ("chunks.json", "lexical.json", "vectors.npy")},
                }
                write_json(stage / "manifest.json", manifest)
                os.replace(stage, self.index_dir / version)
                pointer = self.index_dir / (".current_" + uuid.uuid4().hex + ".json")
                try:
                    write_json(pointer, {"index_version": version})
                    os.replace(pointer, self.index_dir / "current.json")
                finally:
                    pointer.unlink(missing_ok=True)
                self._snapshot = (chunks, vectors, lexical, manifest)
                return copy.deepcopy(manifest)
            except ProjectError:
                raise
            except Exception:
                raise ProjectError("INDEX_BUILD_FAILED", "索引构建或保存失败，原有效索引保持可用") from None
            finally:
                if stage.exists():
                    shutil.rmtree(stage)

    def load(self) -> dict:
        with self._lock:
            try:
                pointer = json.loads((self.index_dir / "current.json").read_text(encoding="utf-8"))
                version = pointer["index_version"]
                if not isinstance(version, str) or not re.fullmatch(r"idx_[A-Za-z0-9_]+", version):
                    raise ValueError("索引版本编号不合法")
                path = (self.index_dir / version).resolve()
                if path.parent != self.index_dir:
                    raise ValueError("索引路径不合法")
                manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
                if manifest["contract_version"] != "1.0" or manifest["index_version"] != version:
                    raise ValueError("索引版本或契约不正确")
                if (manifest["embedding_backend"] != self._backend_config()
                        or manifest["normalized"] != self.settings["normalize_embeddings"]
                        or manifest["retrieval_config"] != self._retrieval_config()
                        or manifest["lexical_tokenizer"] != TOKENIZER_VERSION):
                    raise ProjectError("EMBEDDING_MISMATCH", "模型、文字表示、归一化或检索配置与索引不兼容，请在独立环境重新构建索引")
                requested = self.settings["chunking_config"]
                if requested is not None and requested != manifest["chunking_config"]:
                    raise ProjectError("EMBEDDING_MISMATCH", "切块配置与索引不兼容")
                for name in ("chunks.json", "lexical.json", "vectors.npy"):
                    if digest_file(path / name) != manifest["artifacts"][name]:
                        raise ValueError("索引文件完整性检查失败")
                chunks = validate_chunks(json.loads((path / "chunks.json").read_text(encoding="utf-8")))
                normalize_chunking(manifest["chunking_config"], chunks)
                if (manifest["chunk_count"] != len(chunks)
                        or manifest["document_count"] != len({c["doc_id"] for c in chunks})
                        or manifest["corpus_hash"] != hashlib.sha256(canonical(chunks).encode("utf-8")).hexdigest()):
                    raise ValueError("索引统计或语料哈希不正确")
                lex = json.loads((path / "lexical.json").read_text(encoding="utf-8"))
                if lex["tokenizer"] != TOKENIZER_VERSION or len(lex["tokens"]) != len(chunks):
                    raise ValueError("词项索引不正确")
                expected_tokens = [tokenize("\n".join([c["document"]["title"], *c["document"]["topics"], c["text"]])) for c in chunks]
                if lex["tokens"] != expected_tokens:
                    raise ValueError("词项索引与文本快照不一致")
                vectors = np.load(path / "vectors.npy", allow_pickle=False)
                if vectors.shape != (len(chunks), manifest["dimension"]) or not np.isfinite(vectors).all():
                    raise ValueError("向量矩阵不正确")
                norms = np.linalg.norm(vectors.astype(np.float64), axis=1)
                if np.any(norms == 0) or (manifest["normalized"] and not np.allclose(norms, 1, atol=1e-5)):
                    raise ValueError("向量归一化或非零检查失败")
                lexical = BM25(lex["tokens"], self.settings["bm25_k1"], self.settings["bm25_b"])
            except ProjectError:
                raise
            except FileNotFoundError:
                raise ProjectError("INDEX_NOT_READY", "有效索引指针或索引文件不存在") from None
            except Exception:
                raise ProjectError("INDEX_NOT_READY", "索引损坏或结构不正确，原内存快照保持可用") from None
            self._snapshot = (chunks, vectors, lexical, manifest)
            return copy.deepcopy(manifest)

    def get_manifest(self) -> dict | None:
        with self._lock:
            return copy.deepcopy(self._snapshot[3]) if self._snapshot is not None else None

    def get_chunk_ids(self) -> set[str]:
        """评估入口用于校验标注编号；不替代人工语义复核。"""
        with self._lock:
            if self._snapshot is None:
                raise ProjectError("INDEX_NOT_READY", "请先构建或加载索引")
            return {chunk["chunk_id"] for chunk in self._snapshot[0]}

    def get_neighbors(self, chunk_id: str, radius: int = 1, filters: dict | None = None,
                      expected_index_version: str | None = None) -> list[dict]:
        """Optional QA extension: adjacent chunks from this exact index snapshot.

        Reads memory only, across PDF page boundaries when appropriate; individual
        chunks and their page/offset provenance are never rewritten or joined.
        """
        if not isinstance(chunk_id, str) or not chunk_id or type(radius) is not int or not 1 <= radius <= 2:
            raise ProjectError("INVALID_REQUEST", "相邻片段参数非法")
        low, high, topics = validate_filters(filters)
        with self._lock:
            if self._snapshot is None:
                raise ProjectError("INDEX_NOT_READY", "请先构建或加载索引")
            chunks, _, _, manifest = self._snapshot
            if expected_index_version is not None and manifest["index_version"] != expected_index_version:
                raise ProjectError("INDEX_NOT_READY", "相邻片段读取期间索引版本改变")
            anchor = next((c for c in chunks if c["chunk_id"] == chunk_id), None)
            if anchor is None:
                raise ProjectError("INDEX_NOT_READY", "种子片段不在当前索引")
            def eligible(chunk):
                doc = chunk["document"]
                year = doc["year"]
                return not ((low is not None or high is not None) and year is None
                    or low is not None and year < low or high is not None and year > high
                    or topics and not topics.intersection(doc["topics"]))
            if not eligible(anchor):
                return []
            ordered = sorted((c for c in chunks if c["doc_id"] == anchor["doc_id"]),
                             key=lambda c: (c["pdf_page"], c["page_char_start"], c["chunk_id"]))
            position = next(i for i, c in enumerate(ordered) if c["chunk_id"] == chunk_id)
            adjacent = [ordered[i] for i in range(max(0, position - radius), min(len(ordered), position + radius + 1))
                        if i != position and eligible(ordered[i])]
            return [dict(rank=i + 1, chunk=copy.deepcopy(chunk),
                         scores=dict(bm25=None, cosine=None, rrf=None, rerank=None), matched_by=[],
                         index_version=manifest["index_version"]) for i, chunk in enumerate(adjacent)]

    def search(self, query: str, filters: dict | None = None,
               mode: str = "hybrid", top_k: int = 20) -> list[dict]:
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 2000:
            raise ProjectError("INVALID_REQUEST", "查询去除首尾空白后须为 1–2000 个字符")
        if mode not in ("keyword", "vector", "hybrid"):
            raise ProjectError("INVALID_REQUEST", "检索模式必须为 keyword/vector/hybrid")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= 50:
            raise ProjectError("INVALID_REQUEST", "top_k 必须为 1–50")
        low, high, topics = validate_filters(filters)
        with self._lock:
            if self._snapshot is None:
                raise ProjectError("INDEX_NOT_READY", "请先构建或加载索引")
            chunks, vectors, lexical, manifest = self._snapshot
            eligible = []
            for index, chunk in enumerate(chunks):
                doc = chunk["document"]
                year = doc["year"]
                if (low is not None or high is not None) and year is None:
                    continue
                if low is not None and year < low or high is not None and year > high:
                    continue
                if topics and not topics.intersection(doc["topics"]):
                    continue
                eligible.append(index)
            if not eligible:
                return []
            branch_k = max(self.settings["candidate_k"], top_k)
            bm25, cosine = {}, {}
            lexical_ranking, vector_ranking = [], []
            if mode in ("keyword", "hybrid"):
                bm25 = lexical.scores(query.strip(), eligible)
                lexical_ranking = sorted(bm25, key=lambda i: (-bm25[i], chunks[i]["chunk_id"]))[:branch_k]
            if mode in ("vector", "hybrid"):
                if self._backend_config() != manifest["embedding_backend"]:
                    raise ProjectError("EMBEDDING_MISMATCH", "查询模型身份与索引不一致")
                encoded = self._encode([query.strip()], manifest["dimension"])[0]
                selected = vectors[eligible]
                scores = (selected.astype(np.float64) @ encoded.astype(np.float64))
                if not manifest["normalized"]:
                    scores /= np.linalg.norm(selected.astype(np.float64), axis=1) * np.linalg.norm(encoded.astype(np.float64))
                scores = np.clip(scores, -1.0, 1.0)
                cosine = {i: float(score) for i, score in zip(eligible, scores)}
                vector_ranking = sorted(cosine, key=lambda i: (-cosine[i], chunks[i]["chunk_id"]))[:branch_k]
            if mode == "hybrid":
                rrf = reciprocal_rank_fusion([lexical_ranking, vector_ranking], self.settings["rrf_k"])
                ranking = sorted(rrf, key=lambda i: (-rrf[i], chunks[i]["chunk_id"]))
            else:
                rrf = {}
                ranking = lexical_ranking if mode == "keyword" else vector_ranking
            lexical_members, vector_members = set(lexical_ranking), set(vector_ranking)
            return [{"rank": rank, "chunk": copy.deepcopy(chunks[index]),
                     "scores": {"bm25": bm25.get(index) if mode != "vector" else None,
                                "cosine": cosine.get(index) if mode != "keyword" else None,
                                "rrf": rrf.get(index), "rerank": None},
                     "matched_by": (["keyword"] if index in lexical_members else []) + (["vector"] if index in vector_members else []),
                     "index_version": manifest["index_version"]}
                    for rank, index in enumerate(ranking[:top_k], 1)]
