"""FastAPI 异步任务处理接口服务"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date, datetime
from enum import Enum
from time import perf_counter
from typing import Any, AsyncGenerator
from uuid import uuid4

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.config import get_settings
from core.database import SQLiteDatabase
from repositories.api_key_repo import ApiKeyRepository
from repositories.request_log_repo import RequestLogRepository
from repositories.task_repo import TaskRepository
from repositories.user_repo import UserRepository
from schemas.response import error_response
from services.task_service import TaskService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用生命周期管理"""
    settings = get_settings()
    db = SQLiteDatabase(settings.db_path)
    await db.init()

    app.state.db = db
    app.state.user_repo = UserRepository(db)
    app.state.api_key_repo = ApiKeyRepository(db)
    app.state.task_repo = TaskRepository(db)
    app.state.request_log_repo = RequestLogRepository(db)
    app.state.task_service = TaskService(app.state.task_repo)
    app.state.templates = Jinja2Templates(directory=str(settings.base_dir / "ui"))

    yield


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title="异步任务处理接口",
        description="统一、稳定、可扩展的异步任务处理 API 服务",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next: Any) -> Any:
        start = perf_counter()
        request_id = uuid4().hex
        request.state.request_id = request_id
        response: Any | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            repo = getattr(request.app.state, "request_log_repo", None)
            if repo is not None:
                latency_ms = int((perf_counter() - start) * 1000)
                status_code = int(getattr(response, "status_code", 500))
                client_host = request.client.host if request.client else None
                user_agent = request.headers.get("user-agent")
                api_key_id = getattr(request.state, "api_key_id", None)
                user_id = getattr(request.state, "user_id", None)
                try:
                    await repo.log(
                        request_id=request_id,
                        method=request.method,
                        path=request.url.path,
                        status_code=status_code,
                        ip=client_host,
                        user_agent=user_agent,
                        api_key_id=api_key_id,
                        user_id=user_id,
                        latency_ms=latency_ms,
                    )
                except Exception:
                    pass

    from routes import admin_ui, api_keys, auth_api, tasks

    app.include_router(auth_api.router)
    app.include_router(api_keys.router)
    app.include_router(tasks.router)
    app.include_router(admin_ui.router)
    
    # 注册异常处理器
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, general_exception_handler)
    
    return app


def _make_json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Exception):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_make_json_safe(v) for v in value]
    return str(value)


async def validation_exception_handler(
    request: Request, 
    exc: Exception
) -> JSONResponse:
    """请求验证异常处理器"""
    if isinstance(exc, RequestValidationError):
        raw_errors = exc.errors()
    else:
        raw_errors = [{"type": type(exc).__name__, "msg": str(exc)}]
    safe_errors = _make_json_safe(raw_errors)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content=jsonable_encoder(error_response(
            message="请求参数验证失败",
            code=1000,
            data={"errors": safe_errors},
        ).model_dump()),
    )


async def general_exception_handler(
    request: Request, 
    exc: Exception
) -> JSONResponse:
    """通用异常处理器"""
    # 确保异常消息是字符串
    error_message = str(exc)
    # 处理可能的 ValidationError 等复杂异常
    if hasattr(exc, "errors"):
        try:
            errors_obj = getattr(exc, "errors")
            if callable(errors_obj):
                errors = errors_obj()
                error_message = f"{type(exc).__name__}: {errors}"
        except Exception:
            error_message = f"{type(exc).__name__}: {error_message}"
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=jsonable_encoder(error_response(
            message=f"内部服务器错误：{error_message}",
            code=5000,
        ).model_dump()),
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, StarletteHTTPException):
        if request.url.path.startswith("/v1/"):
            return JSONResponse(
                status_code=exc.status_code,
                content=jsonable_encoder(
                    error_response(message=str(exc.detail), code=exc.status_code * 100).model_dump()
                ),
            )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return JSONResponse(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content={"detail": str(exc)})


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
