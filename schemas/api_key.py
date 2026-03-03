from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)


class ApiKeyPublic(BaseModel):
    id: int
    name: str
    prefix: str
    created_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class ApiKeyCreated(BaseModel):
    id: int
    name: str
    prefix: str
    api_key: str
    created_at: datetime
