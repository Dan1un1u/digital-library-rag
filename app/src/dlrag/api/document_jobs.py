"""Bounded document jobs with independently readable stage progress."""
import copy
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from .services import ProjectError


class DocumentJobs:
    def __init__(self, services):
        self.services = services
        self.lock = threading.RLock()
        self.jobs = {}
        self.capacity, self.retention, self.ttl = 2, 16, 900
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document")

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, data, filename, kind="metadata", metadata=None, assist=True, lookup=False):
        with self.lock:
            now = time.monotonic()
            completed = sorted((j for j in self.jobs.values() if j["stage"] in {"done", "error"}), key=lambda j: j["updated"])
            for job in completed:
                if now - job["updated"] > self.ttl or len(self.jobs) >= self.retention:
                    del self.jobs[job["job_id"]]
            if sum(j["stage"] not in {"done", "error"} for j in self.jobs.values()) >= self.capacity:
                raise ProjectError("MODEL_UNAVAILABLE", "文献处理队列已满，请稍后重试。")
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = dict(job_id=job_id, kind=kind, stage="queued", stages=["queued"],
                                     created=now, updated=now, result=None, error=None)
            self.executor.submit(self._run, job_id, data, filename, kind, metadata, assist, lookup)
            return {"job_id": job_id}

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or (job["stage"] in {"done", "error"} and time.monotonic() - job["updated"] > self.ttl):
                raise ProjectError("NOT_FOUND", "文献处理任务不存在或已过期，请重新提交。")
            value = {k: copy.deepcopy(v) for k, v in job.items() if k not in {"created", "updated"}}
            value["elapsed_seconds"] = round((job["updated"] if job["stage"] in {"done", "error"} else time.monotonic()) - job["created"], 1)
            return value

    def _run(self, job_id, data, filename, kind, metadata, assist, lookup):
        def progress(stage):
            with self.lock:
                job = self.jobs[job_id]
                job.update(stage=stage, updated=time.monotonic())
                if job["stages"][-1] != stage:
                    job["stages"].append(stage)
        try:
            progress("file_received")
            root = self.services.settings.data_dir / "tmp"
            root.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=root) as folder:
                path = Path(folder) / "upload.pdf"
                path.write_bytes(data)
                del data
                if kind == "metadata":
                    from dlrag.ingestion.metadata_api import recognize_metadata
                    options = {"lookup": True} if lookup else {}
                    result = recognize_metadata(path, self.services.settings, filename=filename, assist=assist, progress=progress, **options)
                else:
                    result = self.services.ingest(str(path), metadata, progress=progress)
            with self.lock:
                self.jobs[job_id]["result"] = result
                progress("done")
        except Exception as exc:
            code = getattr(exc, "code", "INTERNAL_ERROR")
            # Expose known codes, never exception/provider messages or credentials.
            code = code if code in {"INVALID_PDF", "NO_EXTRACTABLE_TEXT", "UPLOAD_TOO_LARGE", "MODEL_NOT_CONFIGURED", "EMBEDDING_UNAVAILABLE", "EMBEDDING_NOT_CONFIGURED", "EMBEDDING_INVALID_RESPONSE", "INDEX_BUILD_FAILED"} else "INTERNAL_ERROR"
            with self.lock:
                message = ("PDF 正文没有可提取文字。增强识别用于标题和作者等信息，全文导入仍需先完成 OCR。"
                           if code == "NO_EXTRACTABLE_TEXT" else
                           "文献处理未完成，请检查 PDF 和服务配置后重试；已有馆藏仍保留。")
                self.jobs[job_id]["error"] = {"code": code, "message": message}
                progress("error")
