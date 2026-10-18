"""C 的真实 QAEngine 接入 D 的 API：真实 A/B 检索 + C 引擎 + 脚本化 LLM（离线）。"""
from dlrag.api.qa_factory import create_client
from dlrag.api.services import assemble
from dlrag.qa import QAEngine, ScriptedMockLLM, SiliconFlowLLM
from dlrag.shared.config import Settings
from dlrag.shared.models import AnswerResponse


def plan(q, **kw):
    base = dict(original_query=q, intent="explain", rewritten_query=q, keywords=[],
                needs_clarification=False, clarification_question=None, clarification_options=[])
    base.update(kw)
    return base


def use_c(services, outputs):
    llm = ScriptedMockLLM(outputs)
    services.qa = QAEngine(services.retriever, llm, {"retrieval_mode": "keyword"})
    return llm


def first_chunk(client, imported):
    hits = client.post("/search", json={"query": "BM25", "mode": "keyword", "top_k": 5}).json()["hits"]
    assert hits
    return hits[0]["chunk"]["chunk_id"]


def test_c_answered_through_api(client, imported, services):
    cid = first_chunk(client, imported)
    llm = use_c(services, [plan("BM25 是什么？"),
                           {"status": "answered", "claims": [{"text": "BM25 是词法检索评分。", "evidence_chunk_ids": [cid]}],
                            "limitations": []}])
    r = client.post("/ask", json={"question": "BM25 是什么？"})
    assert r.status_code == 200, r.text
    body = r.json()
    AnswerResponse.model_validate(body)
    assert body["status"] == "answered" and body["evidence"][0]["chunk_id"] == cid
    assert body["index_version"] == imported["index_version"]
    # 引用可经 D 的受控端点解析回原文和 PDF
    ev = body["evidence"][0]
    assert client.get(f"/chunks/{ev['chunk_id']}").json()["chunk"]["text"] == ev["quote"]
    assert client.get(ev["file_url"].split("#")[0]).status_code == 200
    assert len(llm.calls) == 2


def test_c_clarification_and_fabricated_citation(client, imported, services):
    use_c(services, [plan("那个系统", intent="clarify", needs_clarification=True,
                          clarification_question="指哪个系统？", clarification_options=["检索系统", "馆藏系统"])])
    body = client.post("/ask", json={"question": "那个系统"}).json()
    assert body["status"] == "needs_clarification" and body["clarification_options"]
    bad = {"status": "answered", "claims": [{"text": "x", "evidence_chunk_ids": ["fabricated"]}], "limitations": []}
    use_c(services, [plan("BM25"), bad, bad])
    r = client.post("/ask", json={"question": "BM25"})
    assert r.status_code == 500 and r.json()["error"]["code"] == "OUTPUT_VALIDATION_FAILED"


def test_c_insufficient_and_timeout(client, imported, services):
    use_c(services, [plan("BM25"), {"status": "insufficient_evidence", "claims": [], "limitations": ["证据未覆盖"]}])
    body = client.post("/ask", json={"question": "BM25"}).json()
    assert body["status"] == "insufficient_evidence" and body["limitations"]
    from dlrag.qa.errors import ProjectError
    use_c(services, [plan("BM25"), ProjectError("MODEL_TIMEOUT", "超时")])
    r = client.post("/ask", json={"question": "BM25"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "MODEL_TIMEOUT"


def test_factory_builds_siliconflow_client():
    s = Settings(app_mode="real", llm_base_url="https://api.siliconflow.cn/v1", llm_model="Qwen/Qwen2.5-7B-Instruct",
                 llm_api_key="sk-test", _env_file=None)
    client = create_client(s)
    assert isinstance(client, SiliconFlowLLM) and client.max_output_tokens == 1000
    assert "sk-test" not in str(client.get_config())


def test_real_assembly_uses_c_engine(tmp_path):
    s = Settings(app_mode="real", data_dir=tmp_path, llm_base_url="https://api.siliconflow.cn/v1",
                 llm_model="Qwen/Qwen2.5-7B-Instruct", llm_api_key="sk-test", siliconflow_api_key="sk-emb",
                 llm_client_factory="dlrag.api.qa_factory:create_client", _env_file=None)
    services = assemble(s)
    assert isinstance(services.qa, QAEngine) and services.llm_configured
    assert not [i for i in services.issues if i["component"] == "C"]
    h = services.health()
    assert h["active_models"]["qa_engine"] == "dlrag.qa.engine.QAEngine"
    assert "sk-test" not in str(h)


def test_custom_model_budget_reaches_factory_and_engine(tmp_path):
    s = Settings(app_mode="real", data_dir=tmp_path, llm_base_url="https://api.siliconflow.cn/v1",
                 llm_model="configured-test-model", llm_api_key="test-private",
                 siliconflow_api_key="test-embedding", llm_client_factory="dlrag.api.qa_factory:create_client",
                 llm_max_output_tokens=512, llm_context_window_tokens=8192, _env_file=None)
    client = create_client(s)
    assert client.max_output_tokens == 512 and client.context_window_tokens == 8192
    services = assemble(s)
    assert services.qa.settings["max_output_tokens"] == 512
    assert services.qa.settings["context_window_tokens"] == 8192
    assert "test-private" not in str(services.health())


def test_invalid_model_budget_is_rejected():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Settings(app_mode="real", llm_max_output_tokens=2048, llm_context_window_tokens=1024, _env_file=None)


def test_model_budget_reads_env_strings(monkeypatch):
    monkeypatch.setenv("LLM_MAX_OUTPUT_TOKENS", "512")
    monkeypatch.setenv("LLM_CONTEXT_WINDOW_TOKENS", "8192")
    s = Settings(app_mode="real", _env_file=None)
    assert s.llm_max_output_tokens == 512 and s.llm_context_window_tokens == 8192
