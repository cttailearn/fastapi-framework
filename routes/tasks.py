"""任务 API 路由"""
from __future__ import annotations

from typing import Dict, Any

from fastapi import APIRouter, Depends, status, Response, UploadFile
from fastapi.requests import Request

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
    description="创建一个新的异步任务"
)
async def submit_task(
    request: Request,
    service: TaskService = Depends(get_task_service),
    api_key: AuthenticatedApiKey = api_key_dependency,
) -> APIResponse[TaskResponse]:
    """提交任务接口（支持 JSON 和 multipart/form-data）"""
    import json
    
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

        file_value = form.get("file")
        if isinstance(file_value, UploadFile) and file_value.filename:
            file_content = await file_value.read()
            if task_submit.data is None:
                task_submit.data = {}
            elif isinstance(task_submit.data, str):
                task_submit.data = {"content": task_submit.data}
            task_submit.data["filename"] = file_value.filename
            task_submit.data["content_type"] = file_value.content_type
            task_submit.data["size"] = len(file_content)
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
