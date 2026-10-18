"""真实服务适配器的离线故障、批量、鉴权和响应验证。"""

import json

import numpy as np
import pytest
import requests

from dlrag.retrieval import ProjectError
from dlrag.retrieval.embeddings import SiliconFlowEmbedding, read_env_file


class Response:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.payload = payload
    def json(self):
        if isinstance(self.payload, Exception): raise self.payload
        return self.payload


def payload(rows=2, dimension=2):
    return {"model": "BAAI/bge-m3", "data": [
        {"index": i, "embedding": [i + 1] * dimension} for i in range(rows)],
        "usage": {"total_tokens": rows * 3}}


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception): raise response
        return response


def test_batch_reordering_and_public_descriptor():
    first = payload()
    first["data"].reverse()
    session = Session([Response(payload=first), Response(payload=payload(1))])
    backend = SiliconFlowEmbedding(api_key="测试秘密", dimension=2, batch_size=2, session=session)
    vectors = backend.encode(["中文", "English", "BM25"])
    assert vectors.tolist() == [[1, 1], [2, 2], [1, 1]]
    assert backend.stats["requests"] == 2 and backend.stats["total_tokens"] == 9
    assert "测试秘密" not in json.dumps(backend.get_config(), ensure_ascii=False)
    assert session.calls[0][1]["allow_redirects"] is False
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer 测试秘密"


def test_environment_alias_file_never_executes_shell(tmp_path, monkeypatch):
    monkeypatch.delenv("SILICONFLOW_API_KEY", raising=False)
    monkeypatch.delenv("SD_EMBEDDING_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("# 注释\nexport SD_EMBEDDING_KEY='测试值'\nNOT_RUN=$(touch bad)\n")
    assert read_env_file(path)["NOT_RUN"] == "$(touch bad)"
    backend = SiliconFlowEmbedding.from_env(path)
    assert backend._api_key == "测试值"
    monkeypatch.setenv("SILICONFLOW_API_KEY", "环境覆盖")
    assert SiliconFlowEmbedding.from_env(path)._api_key == "环境覆盖"
    assert not (tmp_path / "bad").exists()


@pytest.mark.parametrize("file_values,environment,expected", [
    ({"SILICONFLOW_API_KEY": "file-primary"}, {"SD_EMBEDDING_KEY": "env-alias"}, "env-alias"),
    ({"SD_EMBEDDING_KEY": "file-alias"}, {"SILICONFLOW_API_KEY": "env-primary"}, "env-primary"),
    ({"SILICONFLOW_API_KEY": "file-primary", "SD_EMBEDDING_KEY": "file-alias"},
     {"SILICONFLOW_API_KEY": "env-primary", "SD_EMBEDDING_KEY": "env-alias"}, "env-primary"),
    ({"SILICONFLOW_API_KEY": "file-primary", "SD_EMBEDDING_KEY": "file-alias"}, {}, "file-primary"),
    ({"SD_EMBEDDING_KEY": "file-alias"}, {"SILICONFLOW_API_KEY": "", "SD_EMBEDDING_KEY": ""}, "file-alias"),
])
def test_key_source_priority_across_aliases(tmp_path, monkeypatch, file_values, environment, expected):
    for name in ("SILICONFLOW_API_KEY", "SD_EMBEDDING_KEY"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{name}={value}" for name, value in file_values.items()))
    session = Session([Response(payload=payload(1))])
    backend = SiliconFlowEmbedding.from_env(path, dimension=2, session=session)
    backend.encode(["probe"])
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer " + expected


@pytest.mark.parametrize("timeout", ["60", None, {}, [], True, False, 0, -1,
                                    float("nan"), float("inf"), -float("inf"), 10 ** 400])
def test_invalid_timeout_raises_project_error(timeout):
    with pytest.raises(ProjectError) as error:
        SiliconFlowEmbedding(timeout=timeout)
    assert error.value.code == "INVALID_REQUEST"


@pytest.mark.parametrize("status", [401, 403, 400, 302])
def test_errors_do_not_include_provider_body_or_secret(status):
    backend = SiliconFlowEmbedding(api_key="secret", dimension=2, session=Session([Response(status, {"message": "secret"})]))
    with pytest.raises(ProjectError) as error: backend.encode(["q"])
    assert "secret" not in error.value.message


def test_missing_key_no_network_and_empty_input():
    session = Session([])
    backend = SiliconFlowEmbedding(session=session)
    assert backend.encode([]).shape == (0, 1024)
    with pytest.raises(ProjectError) as error: backend.encode(["q"])
    assert error.value.code == "EMBEDDING_NOT_CONFIGURED"
    assert session.calls == []


def test_bounded_retry_then_success():
    sleeps = []
    session = Session([Response(429), requests.Timeout("secret"), Response(payload=payload(1))])
    backend = SiliconFlowEmbedding(api_key="secret", dimension=2, session=session, sleep=sleeps.append)
    assert backend.encode(["q"]).shape == (1, 2)
    assert sleeps == [1, 2] and backend.stats["retries"] == 2


def test_exhausted_retry_no_silent_fake():
    session = Session([Response(503), Response(503)])
    backend = SiliconFlowEmbedding(api_key="secret", session=session, max_retries=1, sleep=lambda _: None)
    with pytest.raises(ProjectError) as error: backend.encode(["q"])
    assert error.value.code == "EMBEDDING_UNAVAILABLE" and len(session.calls) == 2


@pytest.mark.parametrize("kind", ["non_json", "dimension", "zero", "nan", "duplicate_index", "model", "missing"])
def test_bad_service_responses_rejected(kind):
    data = payload()
    if kind == "non_json": data = ValueError()
    if kind == "dimension": data["data"][0]["embedding"] = [1]
    if kind == "zero": data["data"][0]["embedding"] = [0, 0]
    if kind == "nan": data["data"][0]["embedding"] = [float("nan"), 0]
    if kind == "duplicate_index": data["data"][0]["index"] = 1
    if kind == "model": data["model"] = "wrong"
    if kind == "missing": data = {}
    backend = SiliconFlowEmbedding(api_key="secret", dimension=2, session=Session([Response(payload=data)]))
    with pytest.raises(ProjectError) as error: backend.encode(["q", "p"])
    assert error.value.code == "EMBEDDING_INVALID_RESPONSE"


def test_no_silent_truncation_or_insecure_endpoint():
    backend = SiliconFlowEmbedding(api_key="secret", session=Session([]))
    with pytest.raises(ProjectError): backend.encode(["中" * 3000])
    with pytest.raises(ProjectError): backend.encode([""])
    with pytest.raises(ProjectError): SiliconFlowEmbedding(base_url="http://insecure.example/v1")
