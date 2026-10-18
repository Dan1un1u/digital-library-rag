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


def test_progress_reads_work_while_corpus_lock_is_held(client, services, imported):
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
    finally:
        release.set()
    job = wait_done(client, job_id)
    assert job["stage"] == "done" and job["answer"]["status"] == "answered"
    assert job["answer"]["evidence"]


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
