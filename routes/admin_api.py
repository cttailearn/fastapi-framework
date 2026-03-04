from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status

from deps.auth import AuthenticatedUser, get_api_key_repo, get_current_user, get_user_repo
from repositories.api_key_repo import ApiKeyRepository
from repositories.request_log_repo import RequestLogRepository
from repositories.task_repo import TaskRepository
from repositories.user_repo import UserRepository
from schemas.admin import AdminApiKeyPublic, AdminOverviewCounts, AdminRequestLogPublic, AdminTaskDetail, AdminTaskListItem
from schemas.response import APIResponse, success_response
from schemas.task import TaskCancelResponse
from services.task_service import TaskService

router = APIRouter(prefix="/v1/admin", tags=["admin"])


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid data.")


def get_task_repo(request: Request) -> TaskRepository:
    repo = getattr(request.app.state, "task_repo", None)
    if not isinstance(repo, TaskRepository):
        raise RuntimeError("TaskRepository not initialized")
    return repo


def get_request_log_repo(request: Request) -> RequestLogRepository:
    repo = getattr(request.app.state, "request_log_repo", None)
    if not isinstance(repo, RequestLogRepository):
        raise RuntimeError("RequestLogRepository not initialized")
    return repo


def get_task_service(request: Request) -> TaskService:
    service = getattr(request.app.state, "task_service", None)
    if not isinstance(service, TaskService):
        raise RuntimeError("TaskService not initialized")
    return service


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return None


async def require_admin(current: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
    if not current.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin required.")
    return current


@router.get("/overview", response_model=APIResponse[AdminOverviewCounts])
async def admin_overview(
    admin: AuthenticatedUser = Depends(require_admin),
    user_repo: UserRepository = Depends(get_user_repo),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    request_log_repo: RequestLogRepository = Depends(get_request_log_repo),
) -> APIResponse[AdminOverviewCounts]:
    return success_response(
        AdminOverviewCounts(
            users=await user_repo.count_users(),
            api_keys=await api_key_repo.count_keys(),
            tasks=await task_repo.count_tasks(),
            requests=await request_log_repo.count_logs(),
        )
    )


@router.get("/api-keys", response_model=APIResponse[list[AdminApiKeyPublic]])
async def admin_list_api_keys(
    admin: AuthenticatedUser = Depends(require_admin),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> APIResponse[list[AdminApiKeyPublic]]:
    keys = await api_key_repo.list_all_keys()
    out: list[AdminApiKeyPublic] = []
    for k in keys:
        out.append(
            AdminApiKeyPublic(
                id=_as_int(k["id"]),
                user_id=_as_int(k["user_id"]),
                username=str(k["username"]),
                name=str(k["name"]),
                api_key=str(k["api_key"]) if k.get("api_key") is not None else None,
                prefix=str(k["prefix"]),
                created_at=datetime.fromisoformat(str(k["created_at"])),
                revoked_at=_parse_dt(k.get("revoked_at")),
                last_used_at=_parse_dt(k.get("last_used_at")),
            )
        )
    return success_response(out)


@router.get("/tasks", response_model=APIResponse[list[AdminTaskListItem]])
async def admin_list_tasks(
    limit: int = 200,
    admin: AuthenticatedUser = Depends(require_admin),
    task_repo: TaskRepository = Depends(get_task_repo),
) -> APIResponse[list[AdminTaskListItem]]:
    tasks = await task_repo.list_recent(limit=limit)
    out: list[AdminTaskListItem] = []
    for t in tasks:
        out.append(AdminTaskListItem.model_validate(t))
    return success_response(out)


@router.get("/tasks/{task_id}", response_model=APIResponse[AdminTaskDetail])
async def admin_get_task(
    task_id: str,
    admin: AuthenticatedUser = Depends(require_admin),
    task_repo: TaskRepository = Depends(get_task_repo),
) -> APIResponse[AdminTaskDetail]:
    task = await task_repo.get(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return success_response(AdminTaskDetail.model_validate(task))


@router.post("/tasks/{task_id}/cancel", response_model=APIResponse[TaskCancelResponse])
async def admin_cancel_task(
    task_id: str,
    admin: AuthenticatedUser = Depends(require_admin),
    service: TaskService = Depends(get_task_service),
) -> APIResponse[TaskCancelResponse]:
    result = await service.cancel_task(task_id)
    return success_response(result)


@router.delete("/tasks/{task_id}", response_model=APIResponse[None])
async def admin_delete_task(
    task_id: str,
    admin: AuthenticatedUser = Depends(require_admin),
    service: TaskService = Depends(get_task_service),
) -> APIResponse[None]:
    await service.delete_task(task_id)
    return success_response(None)


@router.get("/requests", response_model=APIResponse[list[AdminRequestLogPublic]])
async def admin_list_requests(
    limit: int = 200,
    admin: AuthenticatedUser = Depends(require_admin),
    request_log_repo: RequestLogRepository = Depends(get_request_log_repo),
) -> APIResponse[list[AdminRequestLogPublic]]:
    logs = await request_log_repo.list_recent(limit=limit)
    out: list[AdminRequestLogPublic] = []
    for r in logs:
        out.append(
            AdminRequestLogPublic(
                id=_as_int(r["id"]),
                request_id=str(r["request_id"]),
                ts=datetime.fromisoformat(str(r["ts"])),
                method=str(r["method"]),
                path=str(r["path"]),
                status_code=_as_int(r["status_code"]),
                ip=str(r["ip"]) if r.get("ip") is not None else None,
                user_agent=str(r["user_agent"]) if r.get("user_agent") is not None else None,
                api_key_id=_as_int(r["api_key_id"]) if r.get("api_key_id") is not None else None,
                user_id=_as_int(r["user_id"]) if r.get("user_id") is not None else None,
                latency_ms=_as_int(r["latency_ms"]),
                api_key_prefix=str(r["api_key_prefix"]) if r.get("api_key_prefix") is not None else None,
                username=str(r["username"]) if r.get("username") is not None else None,
            )
        )
    return success_response(out)
