from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status

from auth import AuthenticatedUser, get_api_key_repo, get_current_user
from config import get_settings
from repositories.api_key_repo import ApiKeyRepository
from schemas.api_key import ApiKeyCreateRequest, ApiKeyCreated, ApiKeyPublic
from schemas.response import APIResponse, success_response
from security import api_key_prefix, generate_api_key, hash_api_key

router = APIRouter(prefix="/v1/api-keys", tags=["api-keys"])


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid data.")


def _parse_dt(value: object) -> datetime | None:
    if isinstance(value, str) and value:
        return datetime.fromisoformat(value)
    return None


@router.post("", response_model=APIResponse[ApiKeyCreated], status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    current: AuthenticatedUser = Depends(get_current_user),
    repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> APIResponse[ApiKeyCreated]:
    api_key = generate_api_key()
    settings = get_settings()
    key_hash = hash_api_key(api_key, pepper=settings.secret_key)
    prefix = api_key_prefix(api_key)
    key_id = await repo.create_key(user_id=current.user_id, name=payload.name, key_hash=key_hash, prefix=prefix)
    created_at = datetime.now(timezone.utc)

    return success_response(
        ApiKeyCreated(id=key_id, name=payload.name, prefix=prefix, api_key=api_key, created_at=created_at)
    )


@router.get("", response_model=APIResponse[list[ApiKeyPublic]])
async def list_api_keys(
    current: AuthenticatedUser = Depends(get_current_user),
    repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> APIResponse[list[ApiKeyPublic]]:
    keys = await repo.list_keys(current.user_id)
    out: list[ApiKeyPublic] = []
    for k in keys:
        out.append(
            ApiKeyPublic(
                id=_as_int(k.get("id")),
                name=str(k["name"]),
                prefix=str(k["prefix"]),
                created_at=datetime.fromisoformat(str(k["created_at"])),
                revoked_at=_parse_dt(k.get("revoked_at")),
                last_used_at=_parse_dt(k.get("last_used_at")),
            )
        )
    return success_response(out)


@router.delete("/{key_id}", response_model=APIResponse[None])
async def revoke_api_key(
    key_id: int,
    current: AuthenticatedUser = Depends(get_current_user),
    repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> APIResponse[None]:
    key = await repo.get_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found.")
    if _as_int(key.get("user_id")) != current.user_id and not current.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden.")
    await repo.revoke_key(key_id)
    return success_response(None)
