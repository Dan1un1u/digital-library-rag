from concurrent.futures import ThreadPoolExecutor
import threading
import time
import pytest


def wait_done(client, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = client.get("/ask/jobs/" + job_id).json()
        if job["answer"] is not None:
            return job
        time.sleep(0.01)
    pytest.fail("job failed to finish")


def test_progress_and_health_reads_work_while_corpus_lock_is_held(client, services, imported):
    entered, release = threading.Event(), threading.Event()
    original = services.qa.ask
    def blocked(request, progress):
        progress("planning")
        entered.set()
        assert release.wait(3)
        progress("generation")
        return original(request)
    services.qa.ask_with_progress = blocked
    try:
        response = client.post("/ask/jobs", json={"question": "BM25"})
        assert response.status_code == 202
        job_id = response.json()["job_id"]
        assert entered.wait(2)
        assert not services.lock.acquire(blocking=False)
        job = client.get("/ask/jobs/" + job_id).json()
        assert job["stage"] == "planning" and job["answer"] is None
        assert job["stages"] == ["queued", "waiting", "planning"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                health = pool.submit(client.get, "/health").result(timeout=1)
                assert health.status_code == 200
                assert health.json()["index_version"] == imported["index_version"]
                assert not release.is_set()
            finally:
                release.set()
    finally:
        release.set()
    job = wait_done(client, job_id)
    assert job["stage"] == "done" and job["answer"]["status"] == "answered"
    assert job["answer"]["evidence"]


def test_health_reads_manifest_during_qa_embedding(client, services, imported, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original_ask = services.qa.ask
    original_encode = services.retriever._encode

    def delayed_encode(texts, dimension):
        entered.set()
        assert release.wait(6)
        return original_encode(texts, dimension)

    def ask_with_retrieval(request, progress):
        progress("retrieval")
        assert services.retriever.search(request["question"], mode="vector")
        return original_ask(request)

    monkeypatch.setattr(services.retriever, "_encode", delayed_encode)
    monkeypatch.setattr(services.qa, "ask_with_progress", ask_with_retrieval, raising=False)
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            response = client.post("/ask/jobs", json={"question": "BM25"})
            assert response.status_code == 202
            job_id = response.json()["job_id"]
            assert entered.wait(2)
            health = pool.submit(client.get, "/health").result(timeout=1)
            assert health.status_code == 200
            assert health.json()["index_version"] == imported["index_version"]
            assert client.get(f"/ask/jobs/{job_id}").json()["stage"] == "retrieval"
        finally:
            release.set()

    assert wait_done(client, job_id)["answer"]["status"] == "answered"


def test_queue_capacity_and_safe_exception(client, services, imported):
    jobs = client.app.state.ask_jobs
    jobs.capacity = 1
    entered, release = threading.Event(), threading.Event()
    def broken(request, progress):
        entered.set()
        assert release.wait(3)
        raise RuntimeError("provider secret content")
    services.qa.ask_with_progress = broken
    try:
        job_id = client.post("/ask/jobs", json={"question": "BM25"}).json()["job_id"]
        assert entered.wait(2)
        response = client.post("/ask/jobs", json={"question": "BM25"})
        assert response.status_code == 503
    finally:
        release.set()
    job = wait_done(client, job_id)
    assert job["stage"] == "error"
    assert "provider secret" not in str(job)


def test_job_validation_and_expiration(client, imported):
    assert client.post("/ask/jobs", json={"question": ""}).status_code == 422
    assert client.get("/ask/jobs/unknown").status_code == 404
    job_id = client.post("/ask/jobs", json={"question": "BM25"}).json()["job_id"]
    wait_done(client, job_id)
    jobs = client.app.state.ask_jobs
    with jobs.lock:
        jobs.jobs[job_id]["updated"] -= 901
    assert client.get("/ask/jobs/" + job_id).status_code == 404
