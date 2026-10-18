"""硅基流动真实嵌入适配器；读取配置时不发送网络请求。"""

import hashlib
import math
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import requests

from .errors import ProjectError


def read_env_file(path):
    """读取简单的键值配置；不执行 shell、不改变进程环境、不输出值。"""
    if path is None:
        return {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ProjectError("EMBEDDING_NOT_CONFIGURED", "无法读取指定密钥配置文件") from error
    result = {}
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = line.removeprefix("export ")
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].strip()
        result[name.strip()] = value
    return result


class SiliconFlowEmbedding:
    allow_loopback_http = False
    requires_api_key = True
    def __init__(self, api_key=None, model="BAAI/bge-m3", dimension=1024,
                 base_url="https://api.siliconflow.cn/v1", batch_size=16,
                 timeout=60, max_retries=3, session=None, sleep=time.sleep):
        parsed = urlparse(base_url)
        local = parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if ((parsed.scheme != "https" and not (self.allow_loopback_http and local and parsed.scheme == "http")) or not parsed.netloc or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ProjectError("INVALID_REQUEST", "嵌入接口地址必须使用 HTTPS，且不包含凭证或查询参数")
        if isinstance(dimension, bool) or not isinstance(dimension, int) or dimension < 1:
            raise ProjectError("INVALID_REQUEST", "向量维度必须为正整数")
        if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 64:
            raise ProjectError("INVALID_REQUEST", "嵌入批次大小必须为 1–64")
        if not isinstance(model, str) or not model.strip():
            raise ProjectError("INVALID_REQUEST", "必须提供模型名称")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise ProjectError("INVALID_REQUEST", "超时必须为有限正数")
        try:
            valid_timeout = math.isfinite(timeout) and timeout > 0
        except OverflowError:
            valid_timeout = False
        if not valid_timeout:
            raise ProjectError("INVALID_REQUEST", "超时必须为有限正数")
        if isinstance(max_retries, bool) or not isinstance(max_retries, int) or not 0 <= max_retries <= 5:
            raise ProjectError("INVALID_REQUEST", "重试次数必须为 0–5")
        self._api_key = api_key
        self.model = model
        self.revision = None  # 服务商未提供固定权重修订，不能用本地模型修订冒充。
        self.dimension = dimension
        self.base_url = base_url.rstrip("/")
        self.batch_size = batch_size
        self.timeout, self.max_retries = timeout, max_retries
        self._session = session or requests.Session()
        self._sleep = sleep
        self.stats = {"requests": 0, "retries": 0, "input_texts": 0, "total_tokens": 0}

    @classmethod
    def from_env(cls, env_file=None, **overrides):
        file_config = read_env_file(env_file)
        key = (os.environ.get("SILICONFLOW_API_KEY") or os.environ.get("SD_EMBEDDING_KEY")
               or file_config.get("SILICONFLOW_API_KEY") or file_config.get("SD_EMBEDDING_KEY"))
        config = {**file_config, **os.environ}
        settings = {
            "api_key": key,
            "model": config.get("SILICONFLOW_EMBEDDING_MODEL", "BAAI/bge-m3"),
            "base_url": config.get("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1"),
        }
        settings.update(overrides)
        return cls(**settings)

    def get_config(self):
        return {"provider": "siliconflow", "model": self.model, "revision": self.revision,
                "dimension": self.dimension, "base_url": self.base_url,
                "encoding_format": "float", "input_preprocessing": "original-text-v1",
                "revision_pinned": False}

    def _request(self, texts):
        if self.requires_api_key and not self._api_key:
            raise ProjectError("EMBEDDING_NOT_CONFIGURED", "请配置 SILICONFLOW_API_KEY 或 SD_EMBEDDING_KEY")
        for attempt in range(self.max_retries + 1):
            try:
                self.stats["requests"] += 1
                response = self._session.post(
                    self.base_url + "/embeddings",
                    headers={"Authorization": "Bearer " + self._api_key} if self._api_key else {},
                    json={"model": self.model, "input": texts, "encoding_format": "float"},
                    timeout=self.timeout,
                    allow_redirects=False,
                )
            except requests.RequestException:
                if attempt == self.max_retries:
                    raise ProjectError("EMBEDDING_UNAVAILABLE", "嵌入接口连接失败或超时") from None
                response = None
            if response is not None:
                status = response.status_code
                if status == 200:
                    try:
                        return response.json()
                    except ValueError:
                        raise ProjectError("EMBEDDING_INVALID_RESPONSE", "嵌入接口返回了非 JSON 内容") from None
                if status in (401, 403):
                    raise ProjectError("EMBEDDING_NOT_CONFIGURED", f"嵌入接口鉴权失败（HTTP {status}）")
                if status not in (429, 500, 502, 503, 504):
                    raise ProjectError("EMBEDDING_UNAVAILABLE", f"嵌入接口拒绝请求（HTTP {status}）")
                if attempt == self.max_retries:
                    raise ProjectError("EMBEDDING_UNAVAILABLE", f"嵌入接口限流或服务不可用（HTTP {status}）")
            self.stats["retries"] += 1
            self._sleep(min(2 ** attempt, 8))

    def encode(self, texts):
        if not isinstance(texts, list) or any(not isinstance(t, str) or not t.strip() for t in texts):
            raise ProjectError("INVALID_REQUEST", "嵌入输入必须是非空文本组成的列表")
        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        # 使用 UTF-8 字节数的保守保护阈值，预留特殊词元空间；不静默截断。
        # 此项不冒充模型实际分词计数，A 的计数口径仍记录于索引清单。
        if self.model in ("BAAI/bge-m3", "Pro/BAAI/bge-m3") and any(len(t.encode("utf-8")) > 8000 for t in texts):
            raise ProjectError("INVALID_REQUEST", "文本超出 BGE-M3 保守输入长度保护，须先核验模型分词长度")
        vectors = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start:start + self.batch_size]
            payload = self._request(batch)
            try:
                if payload.get("model", self.model) != self.model:
                    raise ValueError("响应模型与配置不同")
                items = payload["data"]
                if any(isinstance(item["index"], bool) or not isinstance(item["index"], int) for item in items):
                    raise ValueError("响应索引不是整数")
                if len(items) != len(batch) or sorted(item["index"] for item in items) != list(range(len(batch))):
                    raise ValueError("响应行数或索引不正确")
                rows = [item["embedding"] for item in sorted(items, key=lambda item: item["index"])]
                array = np.asarray(rows, dtype=np.float32)
                if array.shape != (len(batch), self.dimension) or not np.isfinite(array).all():
                    raise ValueError("响应向量维度或数值不正确")
                if np.any(np.linalg.norm(array.astype(np.float64), axis=1) == 0):
                    raise ValueError("响应中存在零向量")
                usage = payload.get("usage", {})
                used = usage.get("total_tokens", usage.get("prompt_tokens", 0))
                if isinstance(used, bool) or not isinstance(used, int) or used < 0:
                    raise ValueError("用量字段不正确")
            except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
                raise ProjectError("EMBEDDING_INVALID_RESPONSE", "嵌入接口响应结构、模型或向量不符合约定") from None
            self.stats["input_texts"] += len(batch)
            self.stats["total_tokens"] += used
            vectors.extend(array)
        return np.asarray(vectors, dtype=np.float32)


class LocalBGEEmbedding(SiliconFlowEmbedding):
    """Call the independently deployed FP16 encoder; pin the index to its identity."""
    allow_loopback_http = True
    requires_api_key = False

    def __init__(self, base_url="http://127.0.0.1:18080/v1", revision=None, **kwargs):
        parsed = urlparse(base_url)
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.path.rstrip('/') != '/v1':
            raise ProjectError("INVALID_REQUEST", "本地 BGE 必须使用回环地址和 /v1 路径")
        if not revision or not isinstance(revision, str):
            raise ProjectError("INVALID_REQUEST", "本地 BGE 须固定模型来源修订")
        super().__init__(base_url=base_url, **kwargs)
        self.revision = revision
        self._session.trust_env = False

    def get_config(self):
        return {**super().get_config(), "provider": "local-bge-fp16", "revision_pinned": True,
                "input_preprocessing": "original-text-v1;fp16;cls;l2-float32"}

    def encode(self, texts):
        if texts:
            try:
                response = self._session.get(self.base_url[:-3] + '/health', timeout=self.timeout,
                                             allow_redirects=False)
                if response.status_code != 200:
                    raise ValueError()
                health = response.json()
                if not (health['status'] == 'ready' and health['dtype'] == 'float16'
                        and health['device'].startswith('cuda') and health['model'] == self.model
                        and health['dimension'] == self.dimension
                        and health['source_revision'] == self.revision
                        and health['pooling'] == 'CLS' and health['normalization'] == 'L2'):
                    raise ValueError()
            except (requests.RequestException, KeyError, ValueError, TypeError, AttributeError):
                raise ProjectError("EMBEDDING_UNAVAILABLE", "本地 BGE 未就绪，或权重精度、修订与索引配置不一致") from None
        return super().encode(texts)


class FakeHashEmbedding:
    """明确标记的离线替身，只用于接口演示和测试，不证明语义效果。"""
    model = "fake-sha256-v1"
    revision = "1"

    def __init__(self, dimension=16):
        self.dimension = dimension

    def get_config(self):
        return {"provider": "fake", "model": self.model, "revision": self.revision,
                "dimension": self.dimension, "input_preprocessing": "sha256-v1"}

    def encode(self, texts):
        vectors = []
        for text in texts:
            values = []
            for position in range(self.dimension):
                digest = hashlib.sha256(f"{position}:{text}".encode("utf-8")).digest()
                values.append(int.from_bytes(digest[:4], "big") / (2 ** 32) - 0.5)
            vectors.append(values)
        return np.asarray(vectors, dtype=np.float32).reshape(len(texts), self.dimension)
