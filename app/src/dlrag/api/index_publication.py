"""Recover an index publication interrupted before or after SQLite commits."""
import json
import os
from pathlib import Path

from dlrag.ingestion.errors import ProjectError

_PENDING = ".pending-index-publication.json"


def _read_pointer(path):
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None


def prepare_index_publication(index_dir, doc_ids):
    from dlrag.retrieval.retriever import write_json

    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    intent = index_dir / _PENDING
    if intent.exists():
        raise ProjectError("INDEX_BUILD_FAILED", "请先恢复尚未完成的索引发布。")
    temporary = intent.with_suffix(".tmp")
    write_json(temporary, {"documents": doc_ids, "previous": _read_pointer(index_dir / "current.json")})
    os.replace(temporary, intent)
    return intent


def _restore_pointer(pointer, previous):
    if previous is None:
        pointer.unlink(missing_ok=True)
        return
    temporary = pointer.with_name(".rollback-current.tmp")
    with temporary.open("wb") as stream:
        stream.write(previous.encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, pointer)


def recover_index_publication(library, index_dir):
    index_dir = Path(index_dir)
    intent = index_dir / _PENDING
    if not intent.is_file():
        return False
    record = json.loads(intent.read_text(encoding="utf-8"))
    documents = [library.get_document(doc_id) for doc_id in record["documents"]]
    statuses = {doc["status"] if doc is not None else None for doc in documents}
    if statuses not in ({"ready"}, {"indexing"}):
        raise ProjectError("INDEX_BUILD_FAILED", "索引发布记录与馆藏状态不一致，需要先恢复馆藏。")
    if statuses == {"indexing"}:
        pointer = index_dir / "current.json"
        previous = record["previous"]
        if _read_pointer(pointer) != previous:
            _restore_pointer(pointer, previous)
    intent.unlink()
    return True
