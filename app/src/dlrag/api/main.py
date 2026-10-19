"""python -m dlrag.api.main；本地单进程，禁止多 worker。"""
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from fastapi.exceptions import RequestValidationError, ResponseValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException
from dlrag.shared.config import Settings
from dlrag.shared.models import error_answer
from .services import assemble, http_status


def create_app(settings=None, services=None):
    from .routes import router
    settings = settings or (services.settings if services else Settings())
    from .ask_jobs import AskJobs
    from .document_jobs import DocumentJobs
    service = services or assemble(settings)
    jobs = AskJobs(service)
    document_jobs = DocumentJobs(service)
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            jobs.close()
            document_jobs.close()
    app = FastAPI(title="专题数字图书馆", version="1.5", description="本地可信课堂使用；单进程后端。", lifespan=lifespan)
    app.state.services = service
    app.state.ask_jobs = jobs
    app.state.document_jobs = document_jobs
    app.include_router(router)

    def failure(request, code, message, status):
        payload = error_answer("", code, message) if request.url.path == "/ask" else {"error": {"code": code, "message": message}}
        return JSONResponse(payload, status_code=status)

    @app.exception_handler(RequestValidationError)
    @app.exception_handler(ValidationError)
    async def invalid(request: Request, exc):
        return failure(request, "INVALID_REQUEST", "请求格式不正确：请检查必填项、年份范围、检索模式及参数类型。", 422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc):
        return failure(request, "NOT_FOUND" if exc.status_code == 404 else "INVALID_REQUEST",
                       "地址不存在" if exc.status_code == 404 else "请求无法处理", exc.status_code)

    @app.exception_handler(ResponseValidationError)
    async def bad_response(request: Request, exc):
        return failure(request, "OUTPUT_VALIDATION_FAILED", "模块返回不符合共同契约，请查看联调检查。", 500)

    @app.exception_handler(Exception)
    async def error(request: Request, exc):
        from dlrag.ingestion.fulltext import FulltextReviewRequired
        if isinstance(exc, FulltextReviewRequired):
            return JSONResponse({"error": exc.public_error()}, status_code=422)
        code = getattr(exc, "code", "INTERNAL_ERROR")
        message = getattr(exc, "message", "服务内部错误，请检查本地配置和运行状态。")
        # 防止模块异常意外带出当前配置中的密钥。
        for secret in (settings.llm_api_key, settings.siliconflow_api_key, settings.sd_embedding_key):
            if secret.get_secret_value():
                message = str(message).replace(secret.get_secret_value(), "[已隐藏]")
        return failure(request, code, message, http_status(code))

    return app


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(create_app(), host="127.0.0.1", port=8000, workers=1)
