"""Publish corrected SQLite metadata and its search snapshot as one operation.

If a process exits between index publication and SQLite commit, SQLite rolls
back. The durable intent records which previous pointer to restore on startup.
"""
import json
import os
from pathlib import Path

from dlrag.ingestion.errors import ProjectError
from dlrag.retrieval.retriever import write_json

_RECOVERY_FILE = ".pending-metadata-review.json"


def _write_atomic(path, value):
    temporary = path.with_suffix(".tmp")
    write_json(temporary, value)
    os.replace(temporary, path)


def prepare_recovery(index_dir, doc_id, before, after, previous_index):
    path = Path(index_dir) / _RECOVERY_FILE
    _write_atomic(path, {"doc_id": doc_id, "before": before, "after": after, "previous_index": previous_index})
    return path


def recover_review(library, index_dir):
    index_dir = Path(index_dir)
    intent = index_dir / _RECOVERY_FILE
    if not intent.is_file():
        return False
    record = json.loads(intent.read_text(encoding="utf-8"))
    document = library.get_document(record["doc_id"])
    if document is None or document["updated_at"] not in {record["before"], record["after"]}:
        raise ProjectError("INDEX_BUILD_FAILED", "无法核对未完成的元数据修订，请从一致备份恢复。")
    restored = False
    if document["updated_at"] == record["before"]:
        pointer = index_dir / "current.json"
        previous = {"index_version": record["previous_index"]}
        if not pointer.exists() or json.loads(pointer.read_text(encoding="utf-8")) != previous:
            _write_atomic(pointer, previous)
            restored = True
    intent.unlink()
    return restored


def correct_and_publish(service, doc_id, correction):
    from dlrag.api.services import boundary
    from dlrag.shared.models import Chunk, Document, IndexManifest

    library, retriever = service.require("library"), service.require("retriever")
    with service.lock:
        if recover_review(library, service.settings.index_dir):
            retriever.load()
        current = service.manifest()
        if not current:
            raise ProjectError("INDEX_NOT_READY", "请先加载馆藏索引，再保存元数据修订。")
        original = library.get_document(doc_id)
        if original is None:
            raise ProjectError("NOT_FOUND", "文献不存在。")
        chunks = library.list_chunks()
        intent = None
        try:
            with library.correct_metadata(doc_id, correction) as (document, revision_id):
                if revision_id is not None:
                    snapshot = {key: document[key] for key in ("title", "authors", "year", "topics", "language")}
                    for chunk in chunks:
                        if chunk["doc_id"] == doc_id:
                            chunk["document"] = snapshot
                    candidate = [boundary(Chunk, chunk) for chunk in chunks]
                    intent = prepare_recovery(service.settings.index_dir, doc_id, original["updated_at"],
                                              document["updated_at"], current["index_version"])
                    current = boundary(IndexManifest, retriever.build(candidate))
                result = {"document": boundary(Document, document), "revision_id": revision_id,
                          "index_version": current["index_version"]}
        finally:
            if intent is not None and recover_review(library, service.settings.index_dir):
                retriever.load()
        return result
