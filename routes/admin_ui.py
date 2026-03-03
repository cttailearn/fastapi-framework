from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from auth import AuthenticatedUser, get_api_key_repo, get_user_repo, require_admin_user
from config import get_settings
from repositories.api_key_repo import ApiKeyRepository
from repositories.request_log_repo import RequestLogRepository
from repositories.task_repo import TaskRepository
from repositories.user_repo import UserRepository
from security import api_key_prefix, generate_api_key, hash_api_key, issue_access_token, verify_password

router = APIRouter(prefix="/admin", tags=["admin"])


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid data.")


def get_templates(request: Request) -> Jinja2Templates:
    templates = getattr(request.app.state, "templates", None)
    if not isinstance(templates, Jinja2Templates):
        raise RuntimeError("Templates not initialized")
    return templates


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


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return None


@router.get("/login", response_class=HTMLResponse)
async def admin_login_page(request: Request, templates: Jinja2Templates = Depends(get_templates)) -> HTMLResponse:
    return templates.TemplateResponse("admin/login.html", {"request": request, "error": None})


@router.post("/login")
async def admin_login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    user_repo: UserRepository = Depends(get_user_repo),
) -> Response:
    templates = get_templates(request)
    user = await user_repo.get_by_username(username)
    if user is None:
        return templates.TemplateResponse(
            "admin/login.html", {"request": request, "error": "用户名或密码错误"}, status_code=400
        )
    if not verify_password(password, str(user["password_hash"])):
        return templates.TemplateResponse(
            "admin/login.html", {"request": request, "error": "用户名或密码错误"}, status_code=400
        )
    if not bool(_as_int(user.get("is_admin"))):
        return templates.TemplateResponse(
            "admin/login.html", {"request": request, "error": "需要管理员权限"}, status_code=403
        )

    settings = get_settings()
    token = issue_access_token(
        user_id=_as_int(user.get("id")),
        is_admin=True,
        secret=settings.secret_key,
        ttl_seconds=settings.admin_cookie_ttl_seconds,
    )
    response = RedirectResponse(url="/admin", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        settings.admin_cookie_name,
        token.token,
        max_age=settings.admin_cookie_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/logout")
async def admin_logout(request: Request) -> RedirectResponse:
    settings = get_settings()
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(settings.admin_cookie_name)
    return response


@router.get("", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin: AuthenticatedUser = Depends(require_admin_user),
    templates: Jinja2Templates = Depends(get_templates),
    user_repo: UserRepository = Depends(get_user_repo),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
    task_repo: TaskRepository = Depends(get_task_repo),
    request_log_repo: RequestLogRepository = Depends(get_request_log_repo),
) -> HTMLResponse:
    return templates.TemplateResponse(
        "admin/dashboard.html",
        {
            "request": request,
            "admin": admin,
            "nav": "dashboard",
            "counts": {
                "users": await user_repo.count_users(),
                "api_keys": await api_key_repo.count_keys(),
                "tasks": await task_repo.count_tasks(),
                "requests": await request_log_repo.count_logs(),
            },
        },
    )


@router.get("/api-keys", response_class=HTMLResponse)
async def admin_api_keys(
    request: Request,
    admin: AuthenticatedUser = Depends(require_admin_user),
    templates: Jinja2Templates = Depends(get_templates),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> HTMLResponse:
    keys = await api_key_repo.list_all_keys()
    return templates.TemplateResponse(
        "admin/api_keys.html",
        {"request": request, "admin": admin, "nav": "api_keys", "keys": keys, "new_key": None},
    )


@router.post("/api-keys/create", response_class=HTMLResponse)
async def admin_api_keys_create(
    request: Request,
    name: str = Form(...),
    user_id: int = Form(...),
    admin: AuthenticatedUser = Depends(require_admin_user),
    templates: Jinja2Templates = Depends(get_templates),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> HTMLResponse:
    settings = get_settings()
    api_key = generate_api_key()
    key_hash = hash_api_key(api_key, pepper=settings.secret_key)
    prefix = api_key_prefix(api_key)
    await api_key_repo.create_key(user_id=user_id, name=name, key_hash=key_hash, prefix=prefix)
    keys = await api_key_repo.list_all_keys()
    return templates.TemplateResponse(
        "admin/api_keys.html",
        {"request": request, "admin": admin, "nav": "api_keys", "keys": keys, "new_key": api_key},
    )


@router.post("/api-keys/{key_id}/revoke")
async def admin_api_keys_revoke(
    key_id: int,
    admin: AuthenticatedUser = Depends(require_admin_user),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> RedirectResponse:
    await api_key_repo.revoke_key(key_id)
    return RedirectResponse(url="/admin/api-keys", status_code=status.HTTP_302_FOUND)


@router.get("/tasks", response_class=HTMLResponse)
async def admin_tasks(
    request: Request,
    admin: AuthenticatedUser = Depends(require_admin_user),
    templates: Jinja2Templates = Depends(get_templates),
    task_repo: TaskRepository = Depends(get_task_repo),
) -> HTMLResponse:
    tasks = await task_repo.list_recent(limit=200)
    return templates.TemplateResponse(
        "admin/tasks.html",
        {"request": request, "admin": admin, "nav": "tasks", "tasks": tasks},
    )


@router.post("/tasks/{task_id}/cancel")
async def admin_task_cancel(
    task_id: str,
    admin: AuthenticatedUser = Depends(require_admin_user),
    task_repo: TaskRepository = Depends(get_task_repo),
) -> RedirectResponse:
    ok = await task_repo.cancel(task_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
    return RedirectResponse(url="/admin/tasks", status_code=status.HTTP_302_FOUND)


@router.post("/tasks/{task_id}/delete")
async def admin_task_delete(
    task_id: str,
    admin: AuthenticatedUser = Depends(require_admin_user),
    task_repo: TaskRepository = Depends(get_task_repo),
) -> RedirectResponse:
    await task_repo.delete(task_id)
    return RedirectResponse(url="/admin/tasks", status_code=status.HTTP_302_FOUND)


@router.get("/requests", response_class=HTMLResponse)
async def admin_requests(
    request: Request,
    admin: AuthenticatedUser = Depends(require_admin_user),
    templates: Jinja2Templates = Depends(get_templates),
    request_log_repo: RequestLogRepository = Depends(get_request_log_repo),
) -> HTMLResponse:
    logs = await request_log_repo.list_recent(limit=200)
    for r in logs:
        r["ts_dt"] = _parse_dt(r.get("ts"))
    return templates.TemplateResponse(
        "admin/requests.html",
        {"request": request, "admin": admin, "nav": "requests", "logs": logs},
    )
