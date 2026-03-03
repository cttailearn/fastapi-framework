from __future__ import annotations

from datetime import datetime, timezone

from core.database import SQLiteDatabase


class UserRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self._db = db

    async def count_users(self) -> int:
        row = await self._db.fetchone("SELECT COUNT(1) AS cnt FROM users;")
        if row is None:
            return 0
        return int(row["cnt"])

    async def create_user(self, username: str, password_hash: str, is_admin: bool) -> int:
        now = datetime.now(timezone.utc).isoformat()
        return await self._db.execute_returning_id(
            "INSERT INTO users(username, password_hash, is_admin, created_at) VALUES(?,?,?,?);",
            (username, password_hash, 1 if is_admin else 0, now),
        )

    async def get_by_username(self, username: str) -> dict[str, object] | None:
        row = await self._db.fetchone(
            "SELECT id, username, password_hash, is_admin, created_at FROM users WHERE username=?;",
            (username,),
        )
        if row is None:
            return None
        return dict(row.data)

    async def get_by_id(self, user_id: int) -> dict[str, object] | None:
        row = await self._db.fetchone(
            "SELECT id, username, password_hash, is_admin, created_at FROM users WHERE id=?;",
            (user_id,),
        )
        if row is None:
            return None
        return dict(row.data)
