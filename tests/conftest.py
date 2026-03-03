"""pytest 测试配置"""
from collections.abc import Generator
from typing import Any

import os

import pytest
from fastapi.testclient import TestClient

from core.config import reset_settings
from main import create_app


@pytest.fixture
def client(tmp_path: Any) -> Generator[TestClient, None, None]:
    """创建测试客户端"""
    os.environ["APP_SECRET_KEY"] = "test-secret"
    os.environ["APP_DB_PATH"] = str(tmp_path / "test.sqlite3")
    reset_settings()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def sample_task_data() -> dict[str, Any]:
    """示例任务数据"""
    return {
        "type": "text",
        "data": {"content": "测试文本内容"},
        "config": {"language": "zh"}
    }
