from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    db_path: Path
    secret_key: str
    access_token_ttl_seconds: int
    agent_timeout_seconds: int
    agent_max_retries: int
    agent_heartbeat_seconds: int
    command_timeout_seconds: int
    command_poll_seconds: int
    command_idle_seconds: int


_SETTINGS: Settings | None = None


def get_settings() -> Settings:
    global _SETTINGS
    if _SETTINGS is not None:
        return _SETTINGS

    base_dir = Path(__file__).resolve().parent.parent
    default_db_path = base_dir / "db" / "app.sqlite3"
    db_path = Path(os.getenv("APP_DB_PATH", str(default_db_path))).resolve()
    secret_key = os.getenv("APP_SECRET_KEY", "dev-secret-change-me")
    access_token_ttl_seconds = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", str(60 * 60 * 24)))
    agent_timeout_seconds = int(os.getenv("APP_AGENT_TIMEOUT_SECONDS", str(300)))
    agent_max_retries = int(os.getenv("APP_AGENT_MAX_RETRIES", str(3)))
    agent_heartbeat_seconds = int(os.getenv("APP_AGENT_HEARTBEAT_SECONDS", str(15)))
    command_timeout_seconds = int(os.getenv("APP_COMMAND_TIMEOUT_SECONDS", str(7200)))
    command_poll_seconds = int(os.getenv("APP_COMMAND_POLL_SECONDS", str(5)))
    command_idle_seconds = int(os.getenv("APP_COMMAND_IDLE_SECONDS", str(1800)))

    _SETTINGS = Settings(
        base_dir=base_dir,
        db_path=db_path,
        secret_key=secret_key,
        access_token_ttl_seconds=access_token_ttl_seconds,
        agent_timeout_seconds=agent_timeout_seconds,
        agent_max_retries=agent_max_retries,
        agent_heartbeat_seconds=agent_heartbeat_seconds,
        command_timeout_seconds=command_timeout_seconds,
        command_poll_seconds=command_poll_seconds,
        command_idle_seconds=command_idle_seconds,
    )
    return _SETTINGS


def reset_settings() -> None:
    global _SETTINGS
    _SETTINGS = None

