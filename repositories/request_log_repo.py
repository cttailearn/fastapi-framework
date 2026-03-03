from __future__ import annotations

from datetime import datetime, timezone

from core.database import SQLiteDatabase


class RequestLogRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self._db = db

    async def log(
        self,
        request_id: str,
        method: str,
        path: str,
        status_code: int,
        ip: str | None,
        user_agent: str | None,
        api_key_id: int | None,
        user_id: int | None,
        latency_ms: int,
    ) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        await self._db.execute(
            """
            INSERT INTO request_logs(request_id, ts, method, path, status_code, ip, user_agent, api_key_id, user_id, latency_ms)
            VALUES(?,?,?,?,?,?,?,?,?,?);
            """.strip(),
            (
                request_id,
                ts,
                method,
                path,
                status_code,
                ip,
                user_agent,
                api_key_id,
                user_id,
                latency_ms,
            ),
        )

    async def list_recent(self, limit: int = 200) -> list[dict[str, object]]:
        rows = await self._db.fetchall(
            """
            SELECT r.id, r.request_id, r.ts, r.method, r.path, r.status_code, r.ip, r.user_agent, r.api_key_id, r.user_id, r.latency_ms,
                   k.prefix AS api_key_prefix,
                   u.username AS username
            FROM request_logs r
            LEFT JOIN api_keys k ON k.id = r.api_key_id
            LEFT JOIN users u ON u.id = r.user_id
            ORDER BY r.id DESC
            LIMIT ?;
            """.strip(),
            (limit,),
        )
        return [dict(r.data) for r in rows]

    async def count_logs(self) -> int:
        row = await self._db.fetchone("SELECT COUNT(1) AS cnt FROM request_logs;")
        if row is None:
            return 0
        return int(row["cnt"])
