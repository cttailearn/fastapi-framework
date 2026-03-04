from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import anyio


@dataclass(frozen=True)
class DbRow:
    data: Mapping[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.data[key]


class SQLiteDatabase:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        return self._db_path

    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        await self.execute("PRAGMA foreign_keys = ON;")
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              username TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              is_admin INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL
            );
            """.strip()
        )
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              name TEXT NOT NULL,
              api_key TEXT,
              key_hash TEXT NOT NULL UNIQUE,
              prefix TEXT NOT NULL,
              created_at TEXT NOT NULL,
              revoked_at TEXT,
              last_used_at TEXT
            );
            """.strip()
        )
        cols = await self.fetchall("PRAGMA table_info(api_keys);")
        col_names = {str(r["name"]) for r in cols}
        if "api_key" not in col_names:
            await self.execute("ALTER TABLE api_keys ADD COLUMN api_key TEXT;")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id);")
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              task_id TEXT PRIMARY KEY,
              api_key_id INTEGER REFERENCES api_keys(id),
              user_id INTEGER REFERENCES users(id),
              type TEXT NOT NULL,
              status TEXT NOT NULL,
              progress INTEGER NOT NULL DEFAULT 0,
              data_json TEXT,
              callback TEXT,
              config_json TEXT,
              result_json TEXT,
              error_json TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              completed_at TEXT
            );
            """.strip()
        )
        await self.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);")
        await self.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);")
        await self.execute(
            """
            CREATE TABLE IF NOT EXISTS request_logs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              request_id TEXT NOT NULL,
              ts TEXT NOT NULL,
              method TEXT NOT NULL,
              path TEXT NOT NULL,
              status_code INTEGER NOT NULL,
              ip TEXT,
              user_agent TEXT,
              api_key_id INTEGER REFERENCES api_keys(id),
              user_id INTEGER REFERENCES users(id),
              latency_ms INTEGER NOT NULL
            );
            """.strip()
        )
        await self.execute("CREATE INDEX IF NOT EXISTS idx_request_logs_ts ON request_logs(ts);")

    async def execute(self, query: str, params: Iterable[Any] | None = None) -> None:
        await anyio.to_thread.run_sync(self._execute_sync, query, tuple(params or ()))

    async def execute_returning_id(self, query: str, params: Iterable[Any] | None = None) -> int:
        return await anyio.to_thread.run_sync(
            self._execute_returning_id_sync, query, tuple(params or ())
        )

    async def fetchone(self, query: str, params: Iterable[Any] | None = None) -> DbRow | None:
        row = await anyio.to_thread.run_sync(self._fetchone_sync, query, tuple(params or ()))
        if row is None:
            return None
        return DbRow(data=row)

    async def fetchall(self, query: str, params: Iterable[Any] | None = None) -> list[DbRow]:
        rows = await anyio.to_thread.run_sync(self._fetchall_sync, query, tuple(params or ()))
        return [DbRow(data=r) for r in rows]

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _execute_sync(self, query: str, params: tuple[Any, ...]) -> None:
        with self._connect() as conn:
            conn.execute(query, params)
            conn.commit()

    def _execute_returning_id_sync(self, query: str, params: tuple[Any, ...]) -> int:
        with self._connect() as conn:
            cur = conn.execute(query, params)
            conn.commit()
            last = cur.lastrowid
            if last is None:
                raise RuntimeError("no_lastrowid")
            return int(last)

    def _fetchone_sync(self, query: str, params: tuple[Any, ...]) -> Mapping[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute(query, params)
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row)

    def _fetchall_sync(self, query: str, params: tuple[Any, ...]) -> list[Mapping[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(query, params)
            rows = cur.fetchall()
            return [dict(r) for r in rows]

