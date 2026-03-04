"""任务 API 测试"""
import asyncio
import json
import time
from typing import Any

from fastapi.testclient import TestClient


def _register_and_get_admin_token(client: TestClient) -> str:
    r = client.post("/v1/auth/register", json={"username": "admin", "password": "password-123"})
    assert r.status_code == 201
    assert r.json()["data"]["is_admin"] is True

    r = client.post("/v1/auth/login", json={"username": "admin", "password": "password-123"})
    assert r.status_code == 200
    token = r.json()["data"]["access_token"]
    assert isinstance(token, str) and token
    return token


def _create_api_key(client: TestClient, token: str) -> str:
    r = client.post(
        "/v1/api-keys",
        json={"name": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 201
    api_key = r.json()["data"]["api_key"]
    assert isinstance(api_key, str) and api_key.startswith("ak_")
    return api_key


def _register_and_get_user_token(client: TestClient, username: str) -> str:
    r = client.post("/v1/auth/register", json={"username": username, "password": "password-123"})
    assert r.status_code == 201
    assert r.json()["data"]["is_admin"] is False

    r = client.post("/v1/auth/login", json={"username": username, "password": "password-123"})
    assert r.status_code == 200
    token = r.json()["data"]["access_token"]
    assert isinstance(token, str) and token
    return token


class TestAuthentication:
    def test_tasks_requires_api_key(self, client: TestClient, sample_task_data: dict[str, Any]) -> None:
        response = client.post("/v1/tasks", json=sample_task_data)
        assert response.status_code == 401
        payload = response.json()
        assert payload["code"] != 0

    def test_tasks_rejects_invalid_api_key(self, client: TestClient, sample_task_data: dict[str, Any]) -> None:
        response = client.post("/v1/tasks", json=sample_task_data, headers={"X-API-Key": "ak_invalid"})
        assert response.status_code == 403
        payload = response.json()
        assert payload["code"] != 0


class TestSubmitTask:
    def test_submit_task_success(self, client: TestClient, sample_task_data: dict[str, Any]) -> None:
        token = _register_and_get_admin_token(client)
        api_key = _create_api_key(client, token)

        response = client.post("/v1/tasks", json=sample_task_data, headers={"X-API-Key": api_key})
        assert response.status_code == 201
        payload = response.json()
        assert payload["code"] == 0
        data = payload["data"]
        assert data["type"] == "text"
        assert data["status"] == "pending"
        assert "task_id" in data

    def test_submit_task_multipart_with_file(self, client: TestClient) -> None:
        from core.config import get_settings

        token = _register_and_get_admin_token(client)
        api_key = _create_api_key(client, token)

        settings = get_settings()
        upload_dir = settings.db_path.parent / "uploads"

        response = client.post(
            "/v1/tasks",
            data={"type": "text", "data": json.dumps({"content": "hello"})},
            files={"file": ("hello.txt", b"hello", "text/plain")},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 201
        payload = response.json()
        assert payload["code"] == 0
        assert upload_dir.exists()
        assert any(upload_dir.iterdir())

    def test_submit_task_missing_type(self, client: TestClient) -> None:
        token = _register_and_get_admin_token(client)
        api_key = _create_api_key(client, token)

        response = client.post(
            "/v1/tasks",
            data={"data": json.dumps({"content": "test"})},
            headers={"X-API-Key": api_key},
        )
        assert response.status_code == 400


class TestValidationExceptionHandler:
    def test_validation_exception_handler_serializes_ctx_error(self) -> None:
        from starlette.requests import Request
        from fastapi.exceptions import RequestValidationError

        from main import validation_exception_handler

        scope = {"type": "http", "method": "POST", "path": "/", "headers": []}
        request = Request(scope)
        exc = RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "file"),
                    "msg": "Value error, Expected UploadFile",
                    "input": "",
                    "ctx": {"error": ValueError("Expected UploadFile, received: <class 'str'>")},
                }
            ]
        )

        response = asyncio.run(validation_exception_handler(request, exc))
        assert response.status_code == 400
        payload = json.loads(bytes(response.body).decode("utf-8"))
        assert payload["code"] == 1000
        assert isinstance(payload["data"]["errors"][0]["ctx"]["error"], str)


class TestTaskLifecycle:
    def test_task_full_lifecycle(self, client: TestClient, sample_task_data: dict[str, Any]) -> None:
        token = _register_and_get_admin_token(client)
        api_key = _create_api_key(client, token)

        create_response = client.post("/v1/tasks", json=sample_task_data, headers={"X-API-Key": api_key})
        assert create_response.status_code == 201
        task_id = create_response.json()["data"]["task_id"]

        get_response = client.get(f"/v1/tasks/{task_id}", headers={"X-API-Key": api_key})
        assert get_response.status_code == 200
        assert get_response.json()["data"]["task_id"] == task_id

        time.sleep(3)

        get_response = client.get(f"/v1/tasks/{task_id}", headers={"X-API-Key": api_key})
        assert get_response.status_code == 200
        assert get_response.json()["data"]["status"] == "completed"

        delete_response = client.delete(f"/v1/tasks/{task_id}", headers={"X-API-Key": api_key})
        assert delete_response.status_code == 204

        get_response = client.get(f"/v1/tasks/{task_id}", headers={"X-API-Key": api_key})
        assert get_response.status_code == 404


class TestAdminApi:
    def test_admin_overview_requires_admin(self, client: TestClient) -> None:
        token = _register_and_get_admin_token(client)

        r = client.get("/v1/admin/overview")
        assert r.status_code == 401

        user_token = _register_and_get_user_token(client, "user1")
        r = client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {user_token}"})
        assert r.status_code == 403

        r = client.get("/v1/admin/overview", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        assert payload["data"]["users"] >= 1

    def test_admin_tasks_list(self, client: TestClient, sample_task_data: dict[str, Any]) -> None:
        token = _register_and_get_admin_token(client)
        api_key = _create_api_key(client, token)
        r = client.post("/v1/tasks", json=sample_task_data, headers={"X-API-Key": api_key})
        assert r.status_code == 201

        r = client.get("/v1/admin/tasks", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        assert isinstance(payload["data"], list)

    def test_api_keys_list_returns_full_api_key(self, client: TestClient) -> None:
        token = _register_and_get_admin_token(client)
        api_key = _create_api_key(client, token)

        r = client.get("/v1/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        assert payload["data"][0]["api_key"] == api_key

        r = client.get("/v1/admin/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        assert any(item["api_key"] == api_key for item in payload["data"])

    def test_api_key_hard_delete(self, client: TestClient, sample_task_data: dict[str, Any]) -> None:
        token = _register_and_get_admin_token(client)
        api_key = _create_api_key(client, token)

        r = client.post("/v1/tasks", json=sample_task_data, headers={"X-API-Key": api_key})
        assert r.status_code == 201

        r = client.get("/v1/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        key_id = r.json()["data"][0]["id"]

        r = client.delete(f"/v1/api-keys/{key_id}/hard", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

        r = client.get("/v1/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert all(item["id"] != key_id for item in r.json()["data"])

    def test_api_key_activate_after_revoke(self, client: TestClient) -> None:
        token = _register_and_get_admin_token(client)
        _create_api_key(client, token)
        r = client.get("/v1/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        key_id = r.json()["data"][0]["id"]

        r = client.delete(f"/v1/api-keys/{key_id}", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

        r = client.post(f"/v1/api-keys/{key_id}/activate", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200

        r = client.get("/v1/api-keys", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["data"][0]["revoked_at"] is None

    def test_admin_task_detail(self, client: TestClient, sample_task_data: dict[str, Any]) -> None:
        token = _register_and_get_admin_token(client)
        api_key = _create_api_key(client, token)
        r = client.post("/v1/tasks", json=sample_task_data, headers={"X-API-Key": api_key})
        assert r.status_code == 201
        task_id = r.json()["data"]["task_id"]

        r = client.get(f"/v1/admin/tasks/{task_id}", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        payload = r.json()
        assert payload["code"] == 0
        assert payload["data"]["task_id"] == task_id

    def test_logout_endpoint(self, client: TestClient) -> None:
        token = _register_and_get_admin_token(client)
        r = client.post("/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["code"] == 0
