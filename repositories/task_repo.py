"""任务数据存储仓库（SQLite 实现）"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from core.database import SQLiteDatabase
from schemas.task import TaskStatus


class TaskRepository:
    def __init__(self, db: SQLiteDatabase) -> None:
        self._db = db

    async def create(
        self,
        task_type: str,
        data: dict[str, Any] | str | None = None,
        callback: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
        api_key_id: int | None = None,
        user_id: int | None = None,
    ) -> str:
        """创建新任务"""
        task_id = f"tsk_{uuid4().hex[:10]}"
        now = datetime.now(timezone.utc).isoformat()

        data_json = json.dumps(data, ensure_ascii=False) if data is not None else None
        config_json = json.dumps(config, ensure_ascii=False) if config is not None else None
        await self._db.execute(
            """
            INSERT INTO tasks(task_id, api_key_id, user_id, type, status, progress, data_json, callback, config_json, result_json, error_json, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?);
            """.strip(),
            (
                task_id,
                api_key_id,
                user_id,
                task_type,
                TaskStatus.PENDING.value,
                0,
                data_json,
                callback,
                config_json,
                None,
                None,
                now,
                now,
            ),
        )
        return task_id

    async def get(self, task_id: str) -> dict[str, Any] | None:
        row = await self._db.fetchone("SELECT * FROM tasks WHERE task_id=?;", (task_id,))
        if row is None:
            return None
        return self._deserialize_task(dict(row.data))

    async def update(self, task_id: str, **kwargs: Any) -> None:
        if not kwargs:
            return

        updates: list[str] = []
        params: list[Any] = []
        now = datetime.now(timezone.utc).isoformat()

        for key, value in kwargs.items():
            if key in {"data", "config", "result", "error"}:
                column = f"{key}_json"
                updates.append(f"{column}=?")
                params.append(json.dumps(value, ensure_ascii=False) if value is not None else None)
                continue
            if key == "status" and isinstance(value, TaskStatus):
                updates.append("status=?")
                params.append(value.value)
                continue
            if isinstance(value, datetime):
                updates.append(f"{key}=?")
                params.append(value.isoformat())
                continue
            updates.append(f"{key}=?")
            params.append(value)

        updates.append("updated_at=?")
        params.append(now)
        params.append(task_id)

        await self._db.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE task_id=?;", params)

    async def delete(self, task_id: str) -> bool:
        row = await self._db.fetchone("SELECT task_id FROM tasks WHERE task_id=?;", (task_id,))
        if row is None:
            return False
        await self._db.execute("DELETE FROM tasks WHERE task_id=?;", (task_id,))
        return True

    async def cancel(self, task_id: str) -> bool:
        """取消任务"""
        task = await self.get(task_id)
        if task is None:
            return False
        if task["status"] in (TaskStatus.PENDING, TaskStatus.PROCESSING):
            await self.update(task_id, status=TaskStatus.CANCELLED, completed_at=datetime.now(timezone.utc))
            return True
        return False

    async def list_recent(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = await self._db.fetchall(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?;",
            (limit,),
        )
        return [self._deserialize_task(dict(r.data)) for r in rows]

    async def count_tasks(self) -> int:
        row = await self._db.fetchone("SELECT COUNT(1) AS cnt FROM tasks;")
        if row is None:
            return 0
        return int(row["cnt"])

    def _deserialize_task(self, row: dict[str, Any]) -> dict[str, Any]:
        for dt_key in ("created_at", "updated_at", "completed_at"):
            value = row.get(dt_key)
            if isinstance(value, str):
                row[dt_key] = datetime.fromisoformat(value)
        if isinstance(row.get("status"), str):
            row["status"] = TaskStatus(row["status"])
        for json_key, out_key in (
            ("data_json", "data"),
            ("config_json", "config"),
            ("result_json", "result"),
            ("error_json", "error"),
        ):
            raw = row.pop(json_key, None)
            if isinstance(raw, str) and raw != "":
                try:
                    row[out_key] = json.loads(raw)
                except json.JSONDecodeError:
                    row[out_key] = raw
            else:
                row[out_key] = None
        return row
