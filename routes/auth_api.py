from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, status

from auth import AuthenticatedUser, get_current_user, get_user_repo
from config import get_settings
from repositories.user_repo import UserRepository
from schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserPublic
from schemas.response import APIResponse, success_response
from security import hash_password, issue_access_token, verify_password

router = APIRouter(prefix="/v1/auth", tags=["auth"])


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid user.")


@router.post("/register", response_model=APIResponse[UserPublic], status_code=status.HTTP_201_CREATED)
async def register_user(
    payload: RegisterRequest,
    user_repo: UserRepository = Depends(get_user_repo),
) -> APIResponse[UserPublic]:
    existing = await user_repo.get_by_username(payload.username)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists.")

    is_admin = (await user_repo.count_users()) == 0
    try:
        user_id = await user_repo.create_user(
            username=payload.username,
            password_hash=hash_password(payload.password),
            is_admin=is_admin,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already exists.")

    return success_response(
        UserPublic(id=user_id, username=payload.username, is_admin=is_admin),
    )


@router.post("/login", response_model=APIResponse[TokenResponse])
async def login_user(
    payload: LoginRequest,
    user_repo: UserRepository = Depends(get_user_repo),
) -> APIResponse[TokenResponse]:
    user = await user_repo.get_by_username(payload.username)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    if not verify_password(payload.password, str(user["password_hash"])):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")

    settings = get_settings()
    token = issue_access_token(
        user_id=_as_int(user.get("id")),
        is_admin=bool(_as_int(user.get("is_admin"))),
        secret=settings.secret_key,
        ttl_seconds=settings.access_token_ttl_seconds,
    )
    return success_response(
        TokenResponse(access_token=token.token, expires_at=token.expires_at),
    )


@router.get("/me", response_model=APIResponse[UserPublic])
async def get_me(current: AuthenticatedUser = Depends(get_current_user)) -> APIResponse[UserPublic]:
    return success_response(UserPublic(id=current.user_id, username=current.username, is_admin=current.is_admin))
