"""SiliconFlow chat completions adapter, no implicit retries or mock fallback."""
import copy
import json
import math
import os
import time
from typing import Protocol
from urllib.parse import urlparse

import requests

from .errors import ProjectError
from .validation import parse_json


def serialize(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def input_upper_bound(system, payload):
    # Every UTF-8 byte is conservatively budgeted as one token, plus chat framing.
    # This is a bound, not an actual tokenizer measurement.
    return len(system.encode("utf-8")) + len(serialize(payload).encode("utf-8")) + 128


class LLMClient(Protocol):
    def generate_json(self, system_prompt: str, user_payload: dict) -> dict: ...


class SiliconFlowLLM:
    allow_loopback_http = False
    def __init__(self, api_key=None, model="Qwen/Qwen2.5-7B-Instruct",
                 base_url="https://api.siliconflow.cn/v1", timeout=60,
                 max_output_tokens=1000, context_window_tokens=32768, session=None, enable_thinking=None):
        p = urlparse(base_url)
        local = p.hostname in {"127.0.0.1", "localhost", "::1"}
        if (p.scheme != "https" and not (self.allow_loopback_http and local and p.scheme == "http")) or not p.netloc or p.username or p.password or p.query or p.fragment:
            raise ProjectError("INVALID_REQUEST", "LLM 地址必须为不含凭证和参数的 HTTPS 地址")
        if not isinstance(model, str) or not model.strip():
            raise ProjectError("INVALID_REQUEST", "模型名称不能为空")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ProjectError("INVALID_REQUEST", "模型超时必须为有限正数")
        if (type(max_output_tokens) is not int or max_output_tokens < 1 or
                type(context_window_tokens) is not int or context_window_tokens <= max_output_tokens):
            raise ProjectError("INVALID_REQUEST", "模型上下文或输出预算非法")
        self._api_key, self.model, self.base_url = api_key, model, base_url.rstrip("/")
        self.timeout, self.max_output_tokens = timeout, max_output_tokens
        self.context_window_tokens = context_window_tokens
        self._session = session or requests.Session()
        self.records = []
        if enable_thinking is not None and type(enable_thinking) is not bool:
            raise ProjectError('INVALID_REQUEST', '推理模式配置必须为布尔值或空')
        self.enable_thinking = enable_thinking

    @classmethod
    def from_env(cls, **overrides):
        config = dict(api_key=os.getenv("LLM_API_KEY") or os.getenv("SILICONFLOW_API_KEY"),
                      model=os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct"),
                      base_url=os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1"))
        try:
            config.update(timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
                          max_output_tokens=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "1000")),
                          context_window_tokens=int(os.getenv("LLM_CONTEXT_WINDOW_TOKENS", "32768")))
        except ValueError:
            raise ProjectError("INVALID_REQUEST", "LLM 数字配置非法") from None
        thinking = os.getenv('LLM_ENABLE_THINKING')
        if thinking is not None:
            if thinking.strip().lower() not in {'true','false'}:
                raise ProjectError('INVALID_REQUEST','LLM_ENABLE_THINKING 必须为 true 或 false')
            config['enable_thinking'] = thinking.strip().lower() == 'true'
        return cls(**{**config, **overrides})

    def get_config(self):
        return dict(mode="real", provider="siliconflow", model=self.model, base_url=self.base_url,
                    timeout_seconds=self.timeout, max_output_tokens=self.max_output_tokens,
                    context_window_tokens=self.context_window_tokens, retries=0,
                    budget_count_mode="utf8_byte_upper_bound", revision_pinned=False,
                    enable_thinking=self.enable_thinking)

    def build_request(self, messages):
        payload = {"model": self.model, "messages": messages, "stream": False,
                   "temperature": 0, "max_tokens": self.max_output_tokens,
                   "response_format": {"type": "json_object"}}
        if self.enable_thinking is not None:
            payload['enable_thinking'] = self.enable_thinking
        return payload

    def generate_json(self, system_prompt, user_payload):
        if not self._api_key:
            raise ProjectError("MODEL_NOT_CONFIGURED", "请配置 LLM_API_KEY 或 SILICONFLOW_API_KEY")
        if input_upper_bound(system_prompt, user_payload) + self.max_output_tokens > self.context_window_tokens:
            raise ProjectError("INVALID_REQUEST", "输入与输出预算超过配置的模型上下文上限")
        start = time.perf_counter()
        record = {"model": self.model, "status": "error", "elapsed_ms": 0}
        try:
            try:
                payload = self.build_request([
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": serialize(user_payload)}])
                response = self._session.post(self.base_url + "/chat/completions",
                    headers={"Authorization": "Bearer " + self._api_key},
                    json=payload,
                    timeout=self.timeout, allow_redirects=False)
            except requests.Timeout:
                raise ProjectError("MODEL_TIMEOUT", "生成模型请求超时") from None
            except requests.RequestException:
                raise ProjectError("MODEL_UNAVAILABLE", "生成模型连接失败") from None
            record['http_status'] = response.status_code
            if response.status_code in (401, 403):
                raise ProjectError("MODEL_NOT_CONFIGURED", "生成模型鉴权失败，请检查配置")
            if response.status_code != 200:
                raise ProjectError("MODEL_UNAVAILABLE", "生成模型服务未成功响应")
            try:
                body = response.json()
                choice = body["choices"][0]
                content = choice["message"]["content"]
                if choice.get("finish_reason") != "stop" or not isinstance(content, str):
                    raise ValueError()
            except (KeyError, IndexError, TypeError, ValueError):
                raise ProjectError("OUTPUT_VALIDATION_FAILED", "生成模型响应缺失、截断或结构非法") from None
            result = parse_json(content)
            record["status"] = "ok"
            usage = body.get("usage", {})
            record["usage"] = {k: v for k, v in usage.items() if k in
                               {"prompt_tokens", "completion_tokens", "total_tokens"} and type(v) is int} if isinstance(usage, dict) else {}
            return result
        except ProjectError as error:
            record["error_code"] = error.code
            raise
        finally:
            record["elapsed_ms"] = round((time.perf_counter() - start) * 1000, 3)
            self.records.append(record)


class CLIProxyLLM(SiliconFlowLLM):
    """OpenAI chat protocol through the user's loopback-only Codex OAuth proxy."""
    allow_loopback_http = True

    def __init__(self, *args, reasoning_effort='none', **kwargs):
        super().__init__(*args, **kwargs)
        if urlparse(self.base_url).hostname not in {'127.0.0.1', 'localhost', '::1'}:
            raise ProjectError('INVALID_REQUEST', 'CLIProxyAPI 必须使用本机回环地址')
        if reasoning_effort not in {'none', 'low', 'medium', 'high'}:
            raise ProjectError('INVALID_REQUEST', '推理等级非法')
        self.reasoning_effort = reasoning_effort
        self._session.trust_env = False

    def build_request(self, messages):
        return {'model': self.model, 'messages': messages, 'stream': False,
                'max_completion_tokens': self.max_output_tokens,
                'reasoning_effort': self.reasoning_effort,
                'response_format': {'type': 'json_object'}}

    def get_config(self):
        config = super().get_config()
        config.update(provider='cliproxyapi', reasoning_effort=self.reasoning_effort)
        config.pop('enable_thinking', None)
        return config


class ScriptedMockLLM:
    """Explicit offline fixture, never selected by the real adapter."""
    context_window_tokens = 32768
    max_output_tokens = 1000

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def get_config(self):
        return {"mode": "mock", "model": "scripted-mock", "context_window_tokens": 32768}

    def generate_json(self, system_prompt, user_payload):
        self.calls.append((system_prompt, copy.deepcopy(user_payload)))
        if not self.outputs:
            raise ProjectError("MODEL_UNAVAILABLE", "模拟脚本已耗尽")
        item = self.outputs.pop(0)
        if isinstance(item, Exception):
            raise item
        return copy.deepcopy(item)
