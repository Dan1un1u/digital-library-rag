import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from dlrag.api.main import create_app
from dlrag.api.services import ProjectError, assemble
from dlrag.shared.config import Settings
from dlrag.shared.models import AnswerResponse
from scripts.seed_demo import create_pdf


def test_health_and_real_missing_configuration(tmp_path, monkeypatch):
    for name in ["LLM_API_KEY", "SILICONFLOW_API_KEY", "SD_EMBEDDING_KEY"]:
        monkeypatch.delenv(name, raising=False)
    settings = Settings(app_mode="real", data_dir=tmp_path / "real", _env_file=None)
    client = TestClient(create_app(settings), raise_server_exceptions=False)
    health = client.get("/health").json()
    assert health["mode"] == "real" and health["status"] == "not_ready"
    assert health["embedding_configured"] is False and health["llm_configured"] is False
    response = client.post("/ask", json={"question": "问题"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "MODEL_NOT_CONFIGURED"
    AnswerResponse.model_validate(response.json())


def test_explicit_mode_required(monkeypatch):
    from pydantic import ValidationError
    monkeypatch.delenv("APP_MODE", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_real_pdf_pipeline_and_duplicate(client, imported, pdf, services):
    doc = imported["document"]
    assert doc["status"] == "ready" and doc["page_count"] == 2
    before = services.library.list_chunks()
    result = client.post("/documents", files={"file": ("same.pdf", pdf.read_bytes(), "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    assert result.status_code == 200
    assert result.json()["document"]["doc_id"] == doc["doc_id"]
    assert services.library.list_chunks() == before
    assert result.json()["index_version"] == imported["index_version"]
    assert client.get("/documents").json()["documents"][0]["doc_id"] == doc["doc_id"]
    assert client.get(f"/documents/{doc['doc_id']}").status_code == 200
    raw = client.get(f"/documents/{doc['doc_id']}/file")
    assert raw.headers["content-type"] == "application/pdf" and raw.content == pdf.read_bytes()
    search = client.post("/search", json={"query": "Semantic", "mode": "keyword"}).json()
    hit = search["hits"][0]["chunk"]
    assert hit["pdf_page"] == 2
    assert client.get("/chunks/" + hit["chunk_id"]).json()["chunk"]["text"] == hit["text"]
    answer = client.post("/ask", json={"question": "BM25"}).json()
    AnswerResponse.model_validate(answer)
    assert answer["status"] == "answered"
    ev = answer["evidence"][0]
    source = client.get("/chunks/" + ev["chunk_id"]).json()["chunk"]
    assert ev["quote"] == source["text"] and ev["pdf_page"] == source["pdf_page"]
    assert ev["file_url"] == f"/documents/{source['doc_id']}/file#page={source['pdf_page']}"


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid"])
def test_modes_filters_and_aggregation(client, imported, mode):
    result = client.post("/search", json={"query": "search", "mode": mode,
                                         "filters": {"year_from": 2024, "year_to": 2024, "topics": ["合成测试"]}})
    assert result.status_code == 200
    data = result.json()
    assert len(data["hits"]) == 2 and len(data["documents"]) == 1
    assert data["documents"][0]["best_rank"] == 1
    assert data["documents"][0]["preview"] == data["hits"][0]["chunk"]["text"][:300]
    assert all(h["index_version"] == imported["index_version"] for h in data["hits"])
    assert client.post("/search", json={"query": "search", "mode": mode,
                                       "filters": {"year_from": 2025}}).json()["hits"] == []


@pytest.mark.parametrize("path,payload", [
    ("/search", {"query": "  "}), ("/search", {"query": "q", "mode": "other"}),
    ("/search", {"query": "q", "top_k": 51}), ("/search", {"query": "q", "top_k": True}),
    ("/search", {"query": "q", "filters": {"year_from": 2025, "year_to": 2020}}),
    ("/search", {"query": "q", "filters": {"topics": "bad"}}),
    ("/search", {"query": "q", "filters": {"year_from": True}}),
    ("/search", {"query": "a" * 2001}), ("/ask", {"question": "  "}),
    ("/ask", {}), ("/ask", {"question": "q", "filters": {"unknown": 1}}),
])
def test_invalid_requests_have_contract_error(client, path, payload):
    result = client.post(path, json=payload)
    assert result.status_code == 422
    if path == "/ask":
        AnswerResponse.model_validate(result.json())
    assert result.json()["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("metadata", ["{broken", "[]", '{"doc_id":"override"}', '{"year":true}', '{"authors":"x"}'])
def test_invalid_upload_metadata(client, pdf, metadata):
    response = client.post("/documents", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
                           data={"metadata_json": metadata})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_bad_empty_type_oversize_and_cleanup(client, services, pdf, tmp_path):
    bad = client.post("/documents", files={"file": ("bad.pdf", b"broken", "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "INVALID_PDF"
    empty = tmp_path / "empty.pdf"
    create_pdf(empty, [""])
    response = client.post("/documents", files={"file": (empty.name, empty.read_bytes(), "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    assert response.status_code == 422 and response.json()["error"]["code"] == "NO_EXTRACTABLE_TEXT"
    assert client.get("/documents").json()["documents"] == []
    failed = client.get("/documents?include_nonready=true").json()["documents"]
    assert len(failed) == 2 and all(d["status"] == "failed" for d in failed)
    assert client.post("/documents", files={"file": ("a.txt", b"text", "text/plain")}).status_code == 415
    services.settings.max_upload_mb = 1
    assert client.post("/documents", files={"file": ("huge.pdf", b"a" * (1024 * 1024 + 1), "application/pdf")}).status_code == 413
    assert list((services.settings.data_dir / "tmp").iterdir()) == []


@pytest.mark.parametrize("path", ["/documents/missing", "/documents/missing/file", "/chunks/missing", "/not-an-api"])
def test_missing_objects(client, path):
    response = client.get(path)
    assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


def test_file_service_rejects_outside_path(client, imported, services, pdf, monkeypatch):
    monkeypatch.setattr(services.library, "get_file_path", lambda _: str(pdf))
    assert client.get(f"/documents/{imported['document']['doc_id']}/file").status_code == 404


def test_ask_states_and_history(client, imported):
    clarify = client.post("/ask", json={"question": "那个系统"}).json()
    assert clarify["status"] == "needs_clarification" and not clarify["claims"]
    question = "那个系统\n补充选择：" + clarify["clarification_options"][0]
    assert client.post("/ask", json={"question": question}).json()["status"] == "answered"
    insufficient = client.post("/ask", json={"question": "证据不足"}).json()
    assert insufficient["status"] == "insufficient_evidence" and insufficient["claims"] == []
    timeout = client.post("/ask", json={"question": "超时"})
    assert timeout.status_code == 503 and timeout.json()["error"]["code"] == "MODEL_TIMEOUT"
    history = client.post("/ask", json={"question": "问题", "history": [{"role": "user", "content": "q"}]})
    assert history.status_code == 422 and history.json()["error"]["code"] == "UNSUPPORTED_HISTORY"
    for answer in [clarify, insufficient, timeout.json(), history.json()]:
        AnswerResponse.model_validate(answer)


def test_contract_violation_never_masked(client, imported, services, monkeypatch):
    original = services.qa.ask
    def wrong(req):
        answer = original(req)
        answer["claims"][0]["evidence_ids"] = ["ev_forged"]
        return answer
    monkeypatch.setattr(services.qa, "ask", wrong)
    result = client.post("/ask", json={"question": "BM25"})
    assert result.status_code == 500
    assert result.json()["error"]["code"] == "OUTPUT_VALIDATION_FAILED"
    AnswerResponse.model_validate(result.json())


def test_failure_keeps_old_index_and_new_document_retryable(client, imported, services, tmp_path, monkeypatch):
    old_version = imported["index_version"]
    second = tmp_path / "second.pdf"
    create_pdf(second, ["SYNTHETIC second document for index failure."])
    original = services.retriever.build
    def fail(chunks):
        raise ProjectError("INDEX_BUILD_FAILED", "injected failure")
    monkeypatch.setattr(services.retriever, "build", fail)
    result = client.post("/documents", files={"file": (second.name, second.read_bytes(), "application/pdf")}, data={"metadata_json": json.dumps({"topics": ["自然科学"]})})
    assert result.status_code == 500
    assert client.post("/search", json={"query": "BM25", "mode": "keyword"}).json()["index_version"] == old_version
    docs = client.get("/documents?include_nonready=true").json()["documents"]
    pending = next(d for d in docs if d["doc_id"] != imported["document"]["doc_id"])
    assert pending["status"] == "indexing" and pending["error_code"] == "INDEX_BUILD_FAILED"
    monkeypatch.setattr(services.retriever, "build", original)
    services.rebuild()
    assert services.library.get_document(pending["doc_id"])["status"] == "ready"


def test_restart_loads_existing_index_and_store(imported, settings):
    restarted = assemble(settings)
    assert restarted.manifest()["index_version"] == imported["index_version"]
    assert len(restarted.library.list_documents()) == 1
    with TestClient(create_app(services=restarted), raise_server_exceptions=False) as client:
        assert client.post("/search", json={"query": "BM25", "mode": "keyword"}).json()["hits"]


def test_ask_blocks_rebuild_until_request_finishes(imported, services, monkeypatch):
    from dlrag.shared.models import AskRequest
    entered, release, built = threading.Event(), threading.Event(), threading.Event()
    qa_ask, build = services.qa.ask, services.retriever.build
    def slow_ask(req):
        entered.set()
        assert release.wait(5)
        return qa_ask(req)
    def observed_build(chunks):
        built.set()
        return build(chunks)
    monkeypatch.setattr(services.qa, "ask", slow_ask)
    monkeypatch.setattr(services.retriever, "build", observed_build)
    with ThreadPoolExecutor(max_workers=2) as pool:
        answer = pool.submit(services.ask, AskRequest(question="BM25"))
        assert entered.wait(5)
        rebuild = pool.submit(services.rebuild)
        assert not built.wait(.15)
        release.set()
        assert answer.result()["index_version"] == imported["index_version"]
        assert rebuild.result()["index_version"] != imported["index_version"]


def test_feedback_saved_and_secrets_hidden(client, services, imported, monkeypatch):
    from pydantic import SecretStr
    services.settings.llm_api_key = SecretStr("secret-test-value")
    result = client.post("/feedback", json={"request_id": "q_test", "rating": "useful", "comment": "测试"})
    assert result.json() == {"saved": True}
    assert json.loads((services.settings.data_dir / "feedback.jsonl").read_text(encoding="utf-8"))["comment"] == "测试"
    assert "secret-test-value" not in client.get("/health").text
    def fail(_):
        raise ProjectError("MODEL_UNAVAILABLE", "secret-test-value")
    monkeypatch.setattr(services.qa, "ask", fail)
    response = client.post("/ask", json={"question": "BM25"})
    assert response.status_code == 503 and "secret-test-value" not in response.text


def test_real_timeout_does_not_call_scripted_mock(client, services, imported, monkeypatch):
    services.settings.app_mode = "real"
    services.llm_configured = True
    def timeout(_):
        raise ProjectError("MODEL_TIMEOUT", "真实模式注入的故障测试：模型超时")
    monkeypatch.setattr(services.qa, "ask", timeout)
    response = client.post("/ask", json={"question": "BM25"})
    assert response.status_code == 503 and response.json()["error"]["code"] == "MODEL_TIMEOUT"
    assert response.json()["claims"] == []


def test_manifest_without_timezone_rejected(client, services, imported, monkeypatch):
    value = services.retriever.get_manifest()
    value["built_at"] = "2026-10-16T12:00:00"
    monkeypatch.setattr(services.retriever, "get_manifest", lambda: value)
    response = client.get("/health")
    assert response.status_code == 500 and response.json()["error"]["code"] == "OUTPUT_VALIDATION_FAILED"
