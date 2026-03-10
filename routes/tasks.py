"""任务 API 路由"""
from __future__ import annotations

import json
from typing import Any, Dict

from fastapi import APIRouter, Depends, status, Response, HTTPException
from fastapi.requests import Request
from starlette.datastructures import UploadFile

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
                            "message": {"type": "string", "description": "任务文本内容（例如 LAMMPS 模拟需求）"},
                            "messages": {
                                "type": "array",
                                "description": "对话消息列表（role/content）",
                                "items": {
                                    "type": "object",
                                    "required": ["role", "content"],
                                    "properties": {
                                        "role": {"type": "string"},
                                        "content": {"type": "string"},
                                    },
                                },
                            },
                            "config": {
                                "type": "object",
                                "description": "任务配置参数",
                                "properties": {
                                    "runner": {"type": "string", "enum": ["deepagent", "dummy", "echo", "command", "exec"]},
                                    "thread-id": {"type": "string"},
                                    "recursion-limit": {"type": "integer"},
                                    "no-stream": {"type": "boolean"},
                                    "thread_id": {"type": "string"},
                                    "recursion_limit": {"type": "integer"},
                                    "no_stream": {"type": "boolean"},
                                },
                            },
                        },
                    }
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "required": ["type"],
                        "properties": {
                            "type": {"type": "string", "description": "任务类型"},
                            "message": {"type": "string", "description": "任务文本内容（例如 LAMMPS 模拟需求）"},
                            "messages": {"type": "string", "description": "对话消息列表（JSON 字符串）"},
                            "file": {
                                "type": "array",
                                "items": {"type": "string", "format": "binary"},
                                "description": "上传的文件（可重复传 file 字段）",
                            },
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
                            "message": {"type": "string", "description": "任务文本内容（例如 LAMMPS 模拟需求）"},
                            "messages": {"type": "string", "description": "对话消息列表（JSON 字符串）"},
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
    task_submit: TaskSubmit
    files: list[UploadFile] = []
    
    # 判断是 JSON 还是 multipart/form-data
    if "application/json" in content_type:
        try:
            body = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON body",
            )

        type_value = body.get("type")
        if not isinstance(type_value, str) or not type_value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'type' is required",
            )

        message_value = body.get("message")
        if not isinstance(message_value, str) or not message_value.strip():
            message_value = body.get("content") if isinstance(body.get("content"), str) else None
        message_str = message_value.strip() if isinstance(message_value, str) and message_value.strip() else None

        messages_value = body.get("messages")
        messages_list: list[Dict[str, Any]] | None = messages_value if isinstance(messages_value, list) else None

        config_raw = body.get("config")
        config_value: Dict[str, Any] | None = config_raw if isinstance(config_raw, dict) else None
        if config_value is None and isinstance(config_raw, str) and config_raw.strip():
            try:
                loaded = json.loads(config_raw)
                config_value = loaded if isinstance(loaded, dict) else None
            except json.JSONDecodeError:
                config_value = None
        lifted: Dict[str, Any] = {}
        for k in ("thread-id", "recursion-limit", "no-stream", "thread_id", "recursion_limit", "no_stream"):
            if k in body:
                lifted[k] = body.get(k)
        if config_value is None:
            config_value = lifted or None
        elif lifted:
            for k, v in lifted.items():
                config_value.setdefault(k, v)

        task_submit = TaskSubmit(
            type=type_value,
            message=message_str,
            messages=messages_list,
            config=config_value,
        )
    elif "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
        form = await request.form()

        type_value = form.get("type") or form.get("type_")
        if not isinstance(type_value, str) or not type_value.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Field 'type' is required",
            )

        message_value = form.get("message")
        if not isinstance(message_value, str) or not message_value.strip():
            message_value = form.get("content")
        message_str = message_value.strip() if isinstance(message_value, str) and message_value.strip() else None

        messages_value = form.get("messages")
        messages_list = None
        if isinstance(messages_value, str) and messages_value.strip() and messages_value != "string":
            try:
                loaded_messages = json.loads(messages_value)
                messages_list = loaded_messages if isinstance(loaded_messages, list) else None
            except json.JSONDecodeError:
                messages_list = None

        config_value = form.get("config")
        config_dict: Dict[str, Any] | None = None
        if isinstance(config_value, str) and config_value.strip() and config_value != "string":
            try:
                loaded_config = json.loads(config_value)
                config_dict = loaded_config if isinstance(loaded_config, dict) else None
            except json.JSONDecodeError:
                config_dict = None
        lifted = {}
        for k in ("thread-id", "recursion-limit", "no-stream", "thread_id", "recursion_limit", "no_stream"):
            v = form.get(k)
            if v is None:
                continue
            lifted[k] = v
        if config_dict is None:
            config_dict = lifted or None
        elif lifted:
            for k, v in lifted.items():
                config_dict.setdefault(k, v)

        task_submit = TaskSubmit(
            type=type_value,
            message=message_str,
            messages=messages_list,
            config=config_dict,
        )

        for key, value in form.multi_items():
            if key == "file" and isinstance(value, UploadFile):
                files.append(value)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported content type. Use application/json or multipart/form-data.",
        )
    
    task = await service.submit_task(
        task_submit,
        api_key_id=api_key.api_key_id,
        user_id=api_key.user_id,
        uploaded_files=files if ("multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type) else None,
    )
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
