from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from schemas.task import TaskStatus


class AdminOverviewCounts(BaseModel):
    users: int = Field(..., ge=0)
    api_keys: int = Field(..., ge=0)
    tasks: int = Field(..., ge=0)
    requests: int = Field(..., ge=0)


class AdminApiKeyPublic(BaseModel):
    id: int
    user_id: int
    username: str
    name: str
    api_key: str | None = None
    prefix: str
    created_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class AdminRequestLogPublic(BaseModel):
    id: int
    request_id: str
    ts: datetime
    method: str
    path: str
    status_code: int
    ip: str | None = None
    user_agent: str | None = None
    api_key_id: int | None = None
    user_id: int | None = None
    latency_ms: int
    api_key_prefix: str | None = None
    username: str | None = None


class AdminTaskListItem(BaseModel):
    task_id: str
    type: str
    status: TaskStatus
    progress: int | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class AdminTaskDetail(BaseModel):
    task_id: str
    type: str
    status: TaskStatus
    progress: int | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    callback: str | None = None
    data: dict[str, Any] | str | None = None
    config: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
