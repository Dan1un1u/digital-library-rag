import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal
from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse, Response
from dlrag.shared.models import AskRequest, Chunk, Document, Feedback, Filters, Metadata, SearchRequest
from dlrag.shared.disciplines import DisciplineError, require_discipline
from .services import ProjectError, boundary, http_status

router = APIRouter()


def check_discipline(metadata):
    try:
        require_discipline(metadata)
    except DisciplineError as error:
        raise ProjectError(error.code, error.message) from None


@contextmanager
def temporary_pdf(file, service):
    """Apply identical type/size checks to previews and actual imports."""
    if not file.filename or Path(file.filename).suffix.lower() != ".pdf" or file.content_type not in ("application/pdf", "application/octet-stream"):
        raise ProjectError("UNSUPPORTED_FILE", "仅支持 PDF 文件")
    temp_root = service.settings.data_dir / "tmp"
    temp_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=temp_root) as folder:
        path = Path(folder) / "upload.pdf"
        size = 0
        with path.open("wb") as f:
            while block := file.file.read(64 * 1024):
                size += len(block)
                if size > service.settings.max_upload_mb * 1024 * 1024:
                    raise ProjectError("UPLOAD_TOO_LARGE", f"文件超过 {service.settings.max_upload_mb} MB 上限")
                f.write(block)
        yield path


@router.get("/health")
def health(request: Request):
    return request.app.state.services.health()


@router.post("/documents")
def upload(request: Request, file: Annotated[UploadFile, File()], metadata_json: Annotated[str, Form()] = "{}"):
    service = request.app.state.services
    try:
        try:
            raw = json.loads(metadata_json)
        except (ValueError, TypeError):
            raise ProjectError("INVALID_REQUEST", "metadata_json 必须是 JSON 对象") from None
        metadata = Metadata.model_validate(raw).model_dump(exclude_none=True)
        if "title" not in metadata:
            metadata["title"] = Path(file.filename or "upload.pdf").stem + "（待核验）"
        with temporary_pdf(file, service) as path:
            check_discipline(metadata)
            return service.ingest(str(path), metadata)
    finally:
        file.file.close()


@router.post("/documents/metadata")
def metadata_preview(request: Request, file: Annotated[UploadFile, File()], use_api: Annotated[bool, Form()] = True,
                     use_lookup: Annotated[bool, Form()] = False):
    """Suggest metadata without writing library records or building an index."""
    from dlrag.ingestion.metadata_api import recognize_metadata
    try:
        with temporary_pdf(file, request.app.state.services) as path:
            return recognize_metadata(path, request.app.state.services.settings, filename=file.filename, assist=use_api, lookup=use_lookup)
    finally:
        file.file.close()


@router.post("/documents/metadata/jobs", status_code=202)
def metadata_job(request: Request, file: Annotated[UploadFile, File()], use_api: Annotated[bool, Form()] = True,
                 use_lookup: Annotated[bool, Form()] = False):
    try:
        with temporary_pdf(file, request.app.state.services) as path:
            return request.app.state.document_jobs.submit(path.read_bytes(), file.filename, assist=use_api, lookup=use_lookup)
    finally:
        file.file.close()


@router.post("/documents/jobs", status_code=202)
def import_job(request: Request, file: Annotated[UploadFile, File()], metadata_json: Annotated[str, Form()] = "{}"):
    try:
        try:
            raw = json.loads(metadata_json)
        except (ValueError, TypeError):
            raise ProjectError("INVALID_REQUEST", "metadata_json 必须是 JSON 对象") from None
        metadata = Metadata.model_validate(raw).model_dump(exclude_none=True)
        if "title" not in metadata:
            metadata["title"] = Path(file.filename or "upload.pdf").stem + "（待核验）"
        with temporary_pdf(file, request.app.state.services) as path:
            check_discipline(metadata)
            return request.app.state.document_jobs.submit(path.read_bytes(), file.filename, kind="import", metadata=metadata)
    finally:
        file.file.close()


@router.get("/document-jobs/{job_id}")
def document_progress(request: Request, job_id: str):
    return request.app.state.document_jobs.get(job_id)


@router.get("/documents")
def documents(request: Request, year_from: int | None = None, year_to: int | None = None,
              topics: Annotated[list[str] | None, Query()] = None, include_nonready: bool = False):
    service = request.app.state.services
    filters = Filters(year_from=year_from, year_to=year_to, topics=topics or []).model_dump()
    with service.lock:
        docs = service.require("library").list_documents(filters, include_nonready=include_nonready)
        return {"documents": [boundary(Document, d) for d in docs]}


@router.get("/documents/{doc_id}")
def document(request: Request, doc_id: str):
    service = request.app.state.services
    with service.lock:
        doc = service.require("library").get_document(doc_id)
        if not doc:
            raise ProjectError("NOT_FOUND", "文献不存在")
        return {"document": boundary(Document, doc)}


@router.get("/documents/{doc_id}/file")
def document_file(request: Request, doc_id: str):
    path = request.app.state.services.file_path(doc_id)
    return FileResponse(path, media_type="application/pdf", filename=f"{doc_id}.pdf", content_disposition_type="inline")


@router.get("/documents/{doc_id}/cover")
def document_cover(request: Request, doc_id: str):
    from .covers import pdf_cover
    path = request.app.state.services.file_path(doc_id)
    stat = path.stat()
    return Response(pdf_cover(str(path), stat.st_mtime_ns, stat.st_size), media_type="image/png",
                    headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"})


@router.get("/chunks/{chunk_id}")
def chunk(request: Request, chunk_id: str):
    service = request.app.state.services
    with service.lock:
        value = service.require("library").get_chunk(chunk_id)
        if not value:
            raise ProjectError("NOT_FOUND", "片段不存在")
        return {"chunk": boundary(Chunk, value)}


@router.post("/search")
def search(request: Request, body: SearchRequest):
    return request.app.state.services.search(body)


@router.post("/ask")
def ask(request: Request, body: AskRequest):
    value = request.app.state.services.ask(body)
    status = http_status(value["error"]["code"]) if value["status"] == "error" else 200
    return JSONResponse(value, status_code=status)


@router.post("/feedback")
def feedback(request: Request, body: Feedback):
    return request.app.state.services.feedback(body)


@router.post("/ask/jobs", status_code=202)
def submit_ask(request: Request, body: AskRequest):
    return request.app.state.ask_jobs.submit(body)


@router.get("/ask/jobs/{job_id}")
def ask_progress(request: Request, job_id: str):
    return request.app.state.ask_jobs.get(job_id)


@router.get('/sources/{chunk_id}', response_class=HTMLResponse)
def citation_source(request: Request, chunk_id: str,
                    span: Annotated[list[str] | None, Query()] = None, index_version: str | None = None,
                    lang: Literal['zh', 'en'] = 'zh'):
    from .sources import read_source, pdf_preview, source_html
    from dlrag.shared.i18n import use_language, error_message
    try:
        chunk, highlights, path = read_source(request.app.state.services, chunk_id, span or [], index_version)
    except ProjectError as error:
        if lang == 'en':
            with use_language(lang):
                raise ProjectError(error.code, error_message({'code': error.code, 'message': error.message})) from None
        raise
    image, matched = pdf_preview(path, chunk['pdf_page'], highlights)
    return HTMLResponse(source_html(chunk, highlights, image, matched, language=lang), headers={
        'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; img-src data:; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})
