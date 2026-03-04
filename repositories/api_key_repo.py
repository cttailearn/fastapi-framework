from __future__ import annotations

from datetime import datetime, timezone

from core.database import SQLiteDatabase


class ApiKeyRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self._db = db

    async def create_key(self, user_id: int, name: str, api_key: str, key_hash: str, prefix: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        return await self._db.execute_returning_id(
            "INSERT INTO api_keys(user_id, name, api_key, key_hash, prefix, created_at) VALUES(?,?,?,?,?,?);",
            (user_id, name, api_key, key_hash, prefix, now),
        )

    async def list_keys(self, user_id: int) -> list[dict[str, object]]:
        rows = await self._db.fetchall(
            """
            SELECT id, user_id, name, api_key, prefix, created_at, revoked_at, last_used_at
            FROM api_keys
            WHERE user_id=?
            ORDER BY id DESC;
            """.strip(),
            (user_id,),
        )
        return [dict(r.data) for r in rows]

    async def count_keys(self) -> int:
        row = await self._db.fetchone("SELECT COUNT(1) AS cnt FROM api_keys;")
        if row is None:
            return 0
        return int(row["cnt"])

    async def list_all_keys(self) -> list[dict[str, object]]:
        rows = await self._db.fetchall(
            """
            SELECT k.id, k.user_id, u.username, k.name, k.api_key, k.prefix, k.created_at, k.revoked_at, k.last_used_at
            FROM api_keys k
            JOIN users u ON u.id = k.user_id
            ORDER BY k.id DESC;
            """.strip()
        )
        return [dict(r.data) for r in rows]

    async def get_by_id(self, key_id: int) -> dict[str, object] | None:
        row = await self._db.fetchone(
            """
            SELECT id, user_id, name, api_key, prefix, created_at, revoked_at, last_used_at
            FROM api_keys
            WHERE id=?;
            """.strip(),
            (key_id,),
        )
        if row is None:
            return None
        return dict(row.data)

    async def revoke_key(self, key_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("UPDATE api_keys SET revoked_at=? WHERE id=?;", (now, key_id))

    async def activate_key(self, key_id: int) -> None:
        await self._db.execute("UPDATE api_keys SET revoked_at=NULL WHERE id=?;", (key_id,))

    async def delete_key(self, key_id: int) -> None:
        await self._db.execute("UPDATE tasks SET api_key_id=NULL WHERE api_key_id=?;", (key_id,))
        await self._db.execute("UPDATE request_logs SET api_key_id=NULL WHERE api_key_id=?;", (key_id,))
        await self._db.execute("DELETE FROM api_keys WHERE id=?;", (key_id,))

    async def get_active_by_hash(self, key_hash: str) -> dict[str, object] | None:
        row = await self._db.fetchone(
            """
            SELECT id, user_id, name, api_key, prefix, created_at, revoked_at, last_used_at
            FROM api_keys
            WHERE key_hash=? AND revoked_at IS NULL;
            """.strip(),
            (key_hash,),
        )
        if row is None:
            return None
        return dict(row.data)

    async def touch_last_used(self, key_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        await self._db.execute("UPDATE api_keys SET last_used_at=? WHERE id=?;", (now, key_id))
