"""Bounded, in-memory jobs; progress reads never acquire the corpus lock."""
import copy
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from dlrag.shared.models import error_answer
from .services import ProjectError


class AskJobs:
    def __init__(self, services, capacity=8, retention=32, ttl=900):
        self.services, self.capacity, self.retention, self.ttl = services, capacity, retention, ttl
        self.lock = threading.RLock()
        self.jobs = {}
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qa")

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, request):
        with self.lock:
            now = time.monotonic()
            completed = sorted((j for j in self.jobs.values() if j["answer"] is not None), key=lambda j: j["updated"])
            for job in completed:
                if now - job["updated"] > self.ttl or len(self.jobs) >= self.retention:
                    del self.jobs[job["job_id"]]
            if sum(j["answer"] is None for j in self.jobs.values()) >= self.capacity:
                raise ProjectError("MODEL_UNAVAILABLE", "问答队列已满，请稍后重试。")
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = dict(job_id=job_id, stage="queued", answer=None, created=now, updated=now, stages=["queued"])
            self.executor.submit(self._run, job_id, request)
            return {"job_id": job_id}

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or (job["answer"] is not None and time.monotonic() - job["updated"] > self.ttl):
                raise ProjectError("NOT_FOUND", "问答任务不存在或已过期，请重新提交。")
            return dict(job_id=job_id, stage=job["stage"], stages=list(job["stages"]),
                        elapsed_seconds=round((job["updated"] if job["answer"] is not None else time.monotonic()) - job["created"], 1),
                        answer=copy.deepcopy(job["answer"]))

    def _run(self, job_id, request):
        def progress(stage):
            with self.lock:
                job = self.jobs[job_id]
                job.update(stage=stage, updated=time.monotonic())
                if job["stages"][-1] != stage:
                    job["stages"].append(stage)
        try:
            answer = self.services.ask(request, progress=progress)
        except Exception:
            # Never expose exception messages containing provider responses or credentials.
            answer = error_answer(request.question, "INTERNAL_ERROR", "问答任务处理失败，请检查服务状态后重试。")
        with self.lock:
            self.jobs[job_id]["answer"] = answer
            progress("error" if answer["status"] == "error" else "done")
