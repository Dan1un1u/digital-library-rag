"""Bounded document jobs with independently readable stage progress."""
import copy
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

from dlrag.ingestion.fulltext import FulltextReviewRequired, NoExtractableText
from dlrag.ingestion.recovery import RECOVERABLE_TEXT_ERRORS, RECOVERY_MESSAGES
from .services import ProjectError


JOB_ERROR_CODES = {
    *RECOVERABLE_TEXT_ERRORS, *RECOVERY_MESSAGES,
    "INVALID_PDF", "UPLOAD_TOO_LARGE", "MODEL_NOT_CONFIGURED", "EMBEDDING_UNAVAILABLE",
    "EMBEDDING_NOT_CONFIGURED", "EMBEDDING_INVALID_RESPONSE", "INDEX_BUILD_FAILED",
    "DISCIPLINE_REQUIRED", "DISCIPLINE_CONFLICT",
}


class DocumentJobs:
    def __init__(self, services):
        self.services = services
        self.lock = threading.RLock()
        self.jobs = {}
        self.capacity, self.retention, self.ttl = 2, 16, 900
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document")

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, data, filename, kind="metadata", metadata=None, assist=True, lookup=False, *, replaces=None):
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
            self.executor.submit(self._run, job_id, data, filename, kind, metadata, assist, lookup, replaces)
            return {"job_id": job_id}

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or (job["stage"] in {"done", "error"} and time.monotonic() - job["updated"] > self.ttl):
                raise ProjectError("NOT_FOUND", "文献处理任务不存在或已过期，请重新提交。")
            value = {k: copy.deepcopy(v) for k, v in job.items() if k not in {"created", "updated"}}
            value["elapsed_seconds"] = round((job["updated"] if job["stage"] in {"done", "error"} else time.monotonic()) - job["created"], 1)
            return value

    def _run(self, job_id, data, filename, kind, metadata, assist, lookup, replaces):
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
                if kind == "batch":
                    entries = []
                    for index, (raw, metadata) in enumerate(data):
                        path = Path(folder) / f"{index}.pdf"
                        path.write_bytes(raw)
                        entries.append((str(path), metadata))
                    del data
                    result = self.services.ingest_batch(entries, progress=progress)
                else:
                    path = Path(folder) / "upload.pdf"
                    path.write_bytes(data)
                    del data
                    if kind == "metadata":
                        from dlrag.ingestion.metadata_api import recognize_metadata
                        options = {"lookup": True} if lookup else {}
                        result = recognize_metadata(path, self.services.settings, filename=filename, assist=assist, progress=progress, **options)
                    else:
                        options = {"replaces": replaces} if kind == "recovery" else {}
                        result = self.services.ingest(str(path), metadata, progress=progress, **options)
            with self.lock:
                self.jobs[job_id]["result"] = result
                progress("done")
        except Exception as exc:
            code = getattr(exc, "code", "INTERNAL_ERROR")
            # Expose known codes, never exception/provider messages or credentials.
            code = code if code in JOB_ERROR_CODES else "INTERNAL_ERROR"
            message = RECOVERY_MESSAGES.get(code, "文献处理未完成，请检查 PDF 和服务配置后重试；已有馆藏仍保留。")
            error = {"code": code, "message": message}
            if code == "NO_EXTRACTABLE_TEXT":
                error["message"] = "PDF 正文没有可提取文字。增强识别用于标题和作者等信息，全文导入仍需先完成 OCR。"
                if isinstance(exc, NoExtractableText):
                    error["fulltext_review"] = exc.review
            elif code in {"FULLTEXT_REVIEW_REQUIRED", "TEXT_LAYER_REVIEW_REQUIRED"}:
                if isinstance(exc, FulltextReviewRequired):
                    error = exc.public_error()
                else:
                    error["message"] = "文献包含待核对的正文页，未加入检索。请在文献管理查看页码，核对文字层、完成 OCR 或更换文字版后重试。"
            elif code == "DISCIPLINE_REQUIRED":
                error["message"] = "请选择文献所属学科。"
            elif code == "DISCIPLINE_CONFLICT":
                error["message"] = "所属学科只能选择一项，请保留一个学科标签。"
            with self.lock:
                self.jobs[job_id]["error"] = error
                progress("error")
