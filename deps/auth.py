from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from core.config import get_settings
from core.security import hash_api_key, jwt_decode
from repositories.api_key_repo import ApiKeyRepository
from repositories.user_repo import UserRepository

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
BEARER = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: int
    username: str
    is_admin: bool


@dataclass(frozen=True)
class AuthenticatedApiKey:
    api_key_id: int
    user_id: int
    prefix: str


def _as_int(value: object, *, error_detail: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=error_detail)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=error_detail)


def get_user_repo(request: Request) -> UserRepository:
    repo = getattr(request.app.state, "user_repo", None)
    if not isinstance(repo, UserRepository):
        raise RuntimeError("UserRepository not initialized")
    return repo


def get_api_key_repo(request: Request) -> ApiKeyRepository:
    repo = getattr(request.app.state, "api_key_repo", None)
    if not isinstance(repo, ApiKeyRepository):
        raise RuntimeError("ApiKeyRepository not initialized")
    return repo


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(BEARER),
    user_repo: UserRepository = Depends(get_user_repo),
) -> AuthenticatedUser:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")

    settings = get_settings()
    try:
        payload = jwt_decode(credentials.credentials, secret=settings.secret_key)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")

    sub = payload.get("sub")
    if not isinstance(sub, int):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload.")

    user = await user_repo.get_by_id(sub)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")

    is_admin = bool(_as_int(user.get("is_admin"), error_detail="Invalid user."))
    user_id = _as_int(user.get("id"), error_detail="Invalid user.")
    request.state.user_id = user_id
    return AuthenticatedUser(user_id=user_id, username=str(user.get("username", "")), is_admin=is_admin)


async def verify_api_key(
    request: Request,
    api_key: str | None = Depends(API_KEY_HEADER),
    api_key_repo: ApiKeyRepository = Depends(get_api_key_repo),
) -> AuthenticatedApiKey:
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API key. Please provide X-API-Key header.",
        )

    settings = get_settings()
    key_hash = hash_api_key(api_key, pepper=settings.secret_key)
    key = await api_key_repo.get_active_by_hash(key_hash)
    if key is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid API key.")

    api_key_id = _as_int(key.get("id"), error_detail="Invalid API key.")
    user_id = _as_int(key.get("user_id"), error_detail="Invalid API key.")
    request.state.api_key_id = api_key_id
    request.state.user_id = user_id
    await api_key_repo.touch_last_used(api_key_id)
    return AuthenticatedApiKey(api_key_id=api_key_id, user_id=user_id, prefix=str(key.get("prefix", "")))

