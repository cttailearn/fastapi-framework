"""任务 API 路由"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, Depends, status, Response
from fastapi.requests import Request
from starlette.datastructures import UploadFile

from core.config import get_settings
from deps.auth import AuthenticatedApiKey, verify_api_key
from schemas.response import APIResponse, success_response
from schemas.task import TaskSubmit, TaskResponse, TaskCancelResponse
from services.task_service import TaskService

router = APIRouter(prefix="/v1/tasks", tags=["tasks"])

# API Key 认证依赖
api_key_dependency = Depends(verify_api_key)


async def get_task_service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if not isinstance(service, TaskService):
        raise RuntimeError("TaskService not initialized")
    return service


def _uploads_dir() -> Path:
    settings = get_settings()
    upload_dir = settings.db_path.parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return upload_dir


async def _persist_upload(file: UploadFile) -> dict[str, Any]:
    original_name = file.filename or "upload.bin"
    suffix = Path(original_name).suffix
    stored_name = f"{uuid4().hex}{suffix}"
    path = _uploads_dir() / stored_name
    content = await file.read()
    await asyncio.to_thread(path.write_bytes, content)
    return {
        "stored_path": str(path),
        "original_filename": original_name,
        "content_type": file.content_type,
        "size": len(content),
    }


@router.post(
    "",
    response_model=APIResponse[TaskResponse],
    status_code=status.HTTP_201_CREATED,
    summary="提交任务",
    description="创建一个新的异步任务",
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {"type": "string", "description": "任务类型"},
                            "data": {
                                "oneOf": [{"type": "string"}, {"type": "object"}],
                                "description": "任务数据（文本内容或对象）",
                            },
                            "callback": {"type": "string", "description": "回调 URL"},
                            "config": {"type": "object", "description": "任务配置参数"},
                        },
                    }
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {"type": "string", "description": "任务类型"},
                            "data": {"type": "string", "description": "任务数据（JSON 字符串或纯文本）"},
                            "file": {"type": "string", "format": "binary", "description": "上传的文件"},
                            "callback": {"type": "string", "description": "回调 URL"},
                            "config": {"type": "string", "description": "任务配置（JSON 字符串）"},
                        },
                    }
                },
                "application/x-www-form-urlencoded": {
                    "schema": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {"type": "string", "description": "任务类型"},
                            "data": {"type": "string", "description": "任务数据（JSON 字符串或纯文本）"},
                            "callback": {"type": "string", "description": "回调 URL"},
                            "config": {"type": "string", "description": "任务配置（JSON 字符串）"},
                        },
                    }
                },
            },
        }
    },
)
async def submit_task(
    request: Request,
    service: TaskService = Depends(get_task_service),
    api_key: AuthenticatedApiKey = api_key_dependency,
) -> APIResponse[TaskResponse]:
    """提交任务接口（支持 JSON 和 multipart/form-data）"""
    content_type = request.headers.get("content-type", "")
    
    # 判断是 JSON 还是 multipart/form-data
    if "application/json" in content_type:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON body",
            )

        type_value = body.get("type")
        if not isinstance(type_value, str) or not type_value.strip():
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'type' is required",
            )

        task_submit = TaskSubmit(
            type=type_value,
            data=body.get("data"),
            callback=body.get("callback"),
            config=body.get("config"),
        )
    elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()

        type_value = form.get("type") or form.get("type_")
        if not isinstance(type_value, str) or not type_value.strip():
            from fastapi import HTTPException
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'type' is required",
            )

        data_value = form.get("data")
        data_parsed: str | Dict[str, Any] | None
        if isinstance(data_value, str) and data_value.strip():
            data_str = data_value.strip()
            if data_str.startswith("{") and data_str.endswith("}"):
                try:
                    loaded = json.loads(data_str)
                    data_parsed = loaded if isinstance(loaded, dict) else data_str
                except json.JSONDecodeError:
                    data_parsed = data_str
            else:
                data_parsed = data_str
        else:
            data_parsed = None

        callback_value = form.get("callback")
        callback_str = callback_value.strip() if isinstance(callback_value, str) and callback_value.strip() else None

        config_value = form.get("config")
        config_dict: Dict[str, Any] | None = None
        if isinstance(config_value, str) and config_value.strip() and config_value != "string":
            try:
                loaded_config = json.loads(config_value)
                config_dict = loaded_config if isinstance(loaded_config, dict) else None
            except json.JSONDecodeError:
                config_dict = None

        task_submit = TaskSubmit(
            type=type_value,
            data=data_parsed,
            callback=callback_str,
            config=config_dict,
        )

        files: list[UploadFile] = []
        for key, value in form.multi_items():
            if key == "file" and isinstance(value, UploadFile):
                files.append(value)

        stored_files: list[dict[str, Any]] = []
        for file in files:
            if file.filename:
                stored_files.append(await _persist_upload(file))

        if stored_files:
            if task_submit.data is None:
                task_submit.data = {}
            elif isinstance(task_submit.data, str):
                task_submit.data = {"content": task_submit.data}
            task_submit.data["files"] = stored_files
    else:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported content type. Use application/json or multipart/form-data.",
        )
    
    task = await service.submit_task(task_submit, api_key_id=api_key.api_key_id, user_id=api_key.user_id)
    return success_response(task)


@router.get(
    "/{task_id}",
    response_model=APIResponse[TaskResponse],
    summary="查询任务",
    description="获取任务进度和结果",
)
async def get_task(
    task_id: str, 
    service: TaskService = Depends(get_task_service),
    api_key: AuthenticatedApiKey = api_key_dependency,
) -> APIResponse[TaskResponse]:
    """查询任务接口"""
    task = await service.get_task(task_id)
    return success_response(task)


@router.post(
    "/{task_id}/cancel",
    response_model=APIResponse[TaskCancelResponse],
    summary="取消任务",
    description="取消正在处理的任务",
)
async def cancel_task(
    task_id: str, 
    service: TaskService = Depends(get_task_service),
    api_key: AuthenticatedApiKey = api_key_dependency,
) -> APIResponse[TaskCancelResponse]:
    """取消任务接口"""
    result = await service.cancel_task(task_id)
    return success_response(result)


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除任务",
    description="删除任务及其关联数据",
)
async def delete_task(
    task_id: str, 
    service: TaskService = Depends(get_task_service),
    api_key: AuthenticatedApiKey = api_key_dependency,
) -> Response:
    """删除任务接口"""
    await service.delete_task(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
