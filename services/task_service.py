# 主要任务服务类

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import anyio
from fastapi import HTTPException, status
from starlette.datastructures import UploadFile

from core.config import get_settings
from repositories.task_repo import TaskRepository
from schemas.task import TaskCancelResponse, TaskResponse, TaskStatus, TaskSubmit


class TaskService:
    def __init__(self, task_repo: TaskRepository) -> None:
        self._task_repo = task_repo
        self._running: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()
        self._dotenv_loaded = False

    async def submit_task(
        self,
        submit: TaskSubmit,
        api_key_id: int | None = None,
        user_id: int | None = None,
        uploaded_files: list[UploadFile] | None = None,
    ) -> TaskResponse:
        config = self._normalize_run_config(dict(submit.config or {}))

        data: dict[str, Any] | None = None
        messages: list[dict[str, Any]] = []
        if isinstance(getattr(submit, "messages", None), list):
            for m in getattr(submit, "messages"):
                if not isinstance(m, dict):
                    continue
                role = m.get("role")
                content = m.get("content")
                if isinstance(role, str) and role and isinstance(content, str) and content:
                    messages.append({"role": role, "content": content})

        if messages:
            if isinstance(submit.message, str) and submit.message.strip():
                messages.append({"role": "user", "content": submit.message.strip()})
            data = {"messages": messages}
        elif isinstance(submit.message, str) and submit.message.strip():
            data = {"content": submit.message.strip()}

        task_id = await self._task_repo.create(
            task_type=submit.type,
            data=data,
            callback=None,
            config=config if config else None,
            api_key_id=api_key_id,
            user_id=user_id,
        )

        backend_root = str((self._workspace_root() / task_id).resolve())
        Path(backend_root).mkdir(parents=True, exist_ok=True)
        config["backend_root"] = backend_root
        await asyncio.to_thread(self._ensure_task_skills_dir, backend_root)

        if uploaded_files:
            stored_files = await self._persist_uploads(task_id=task_id, backend_root=backend_root, files=uploaded_files)
            if data is None:
                data = {}
            if isinstance(data, dict):
                data["files"] = stored_files

        await self._task_repo.update(task_id, config=config, data=data)

        async with self._lock:
            t = asyncio.create_task(self._run_task(task_id), name=f"task:{task_id}")
            self._running[task_id] = t
            def _on_done(_: asyncio.Task[None], tid: str = task_id) -> None:
                asyncio.create_task(self._forget_task(tid))

            t.add_done_callback(_on_done)

        task = await self._task_repo.get(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Task create failed.")
        enriched = await self._enrich_task(task, running_hint=True)
        return TaskResponse.model_validate(enriched)

    async def get_task(self, task_id: str) -> TaskResponse:
        task = await self._task_repo.get(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        async with self._lock:
            running = self._running.get(task_id)
            running_hint = bool(running is not None and not running.done())
        enriched = await self._enrich_task(task, running_hint=running_hint)
        return TaskResponse.model_validate(enriched)

    async def cancel_task(self, task_id: str) -> TaskCancelResponse:
        ok = await self._task_repo.cancel(task_id)

        async with self._lock:
            running = self._running.get(task_id)
            if running is not None and not running.done():
                running.cancel()

        if not ok:
            task = await self._task_repo.get(task_id)
            if task is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
            return TaskCancelResponse(task_id=task_id, status=task["status"], updated_at=task["updated_at"])

        task = await self._task_repo.get(task_id)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")
        return TaskCancelResponse(task_id=task_id, status=task["status"], updated_at=task["updated_at"])

    async def delete_task(self, task_id: str) -> None:
        async with self._lock:
            running = self._running.get(task_id)
            if running is not None and not running.done():
                running.cancel()
            self._running.pop(task_id, None)

        ok = await self._task_repo.delete(task_id)
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found.")

    async def _forget_task(self, task_id: str) -> None:
        async with self._lock:
            self._running.pop(task_id, None)

    async def enrich_task_for_admin(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = str(task.get("task_id") or "").strip()
        async with self._lock:
            running = self._running.get(task_id)
            running_hint = bool(running is not None and not running.done())
        return await self._enrich_task(task, running_hint=running_hint)

    async def _run_task(self, task_id: str) -> None:
        task = await self._task_repo.get(task_id)
        if task is None:
            return

        config_raw = task.get("config")
        config = cast(dict[str, Any], config_raw) if isinstance(config_raw, dict) else {}
        started_at = config.get("processing_started_at")
        if not isinstance(started_at, str) or not started_at.strip():
            config["processing_started_at"] = datetime.now(timezone.utc).isoformat()

        existing_progress = task.get("progress")
        if not isinstance(existing_progress, int) or existing_progress < 0:
            existing_progress = 0
        await self._task_repo.update(
            task_id,
            status=TaskStatus.PROCESSING,
            progress=max(existing_progress, 1),
            config=config,
            completed_at=None,
            error=None,
        )

        submit_type = str(task.get("type") or "").strip().lower()
        data = task.get("data")

        try:
            runner = config.get("runner")
            if isinstance(runner, str) and runner.strip():
                runner = runner.strip().lower()
            else:
                runner = None

            if runner in {"dummy", "echo"} or submit_type in {"dummy", "echo"}:
                result = await self._run_dummy(task_id, data=data, config=config)
            elif runner in {"command", "exec"}:
                result = await self._run_command(task_id, data=data, config=config)
            else:
                result = await self._run_deepagent(task_id, data=data, config=config)

            status_override = None
            error_override = None
            if isinstance(result, dict):
                status_override = result.pop("__task_status", None)
                error_override = result.pop("__task_error", None)

            status_value = status_override if isinstance(status_override, TaskStatus) else TaskStatus.COMPLETED
            progress_value = 100 if status_value == TaskStatus.COMPLETED else task.get("progress") or 0
            await self._task_repo.update(
                task_id,
                status=status_value,
                progress=progress_value,
                completed_at=datetime.now(timezone.utc),
                result=result,
                error=error_override,
            )
        except asyncio.CancelledError:
            latest = await self._task_repo.get(task_id)
            if latest is not None and latest.get("status") == TaskStatus.CANCELLED:
                raise
            await self._task_repo.update(
                task_id,
                status=TaskStatus.PENDING,
                completed_at=None,
                error={"message": "任务被服务重启/热重载中断，已回到 pending 等待重试"},
            )
            raise
        except Exception as e:
            await self._task_repo.update(
                task_id,
                status=TaskStatus.FAILED,
                completed_at=datetime.now(timezone.utc),
                error={"message": str(e)},
            )

    async def resume_incomplete_tasks(self, limit: int = 50) -> None:
        candidates = await self._task_repo.list_by_status([TaskStatus.PENDING, TaskStatus.PROCESSING], limit=limit)
        for t in candidates:
            task_id = str(t.get("task_id") or "").strip()
            if not task_id:
                continue
            async with self._lock:
                running = self._running.get(task_id)
                if running is not None and not running.done():
                    continue
                runner_task = asyncio.create_task(self._run_task(task_id), name=f"task:{task_id}")
                self._running[task_id] = runner_task
                def _on_done(_: asyncio.Task[None], tid: str = task_id) -> None:
                    asyncio.create_task(self._forget_task(tid))

                runner_task.add_done_callback(_on_done)

    def _ensure_dotenv_loaded(self) -> None:
        if self._dotenv_loaded:
            return
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except Exception:
            pass
        self._dotenv_loaded = True

    def _can_run_deepagent(self) -> bool:
        self._ensure_dotenv_loaded()
        return bool(os.getenv("OPENAI_API_KEY")) and bool(os.getenv("OPENAI_API_MODEL"))

    def _workspace_root(self) -> Path:
        settings = get_settings()
        return settings.base_dir / "workspace"

    def _ensure_task_skills_dir(self, backend_root: str) -> None:
        src = (Path(__file__).resolve().parent / "agents" / "skills").resolve()
        if not src.exists() or not src.is_dir():
            return
        dest = (Path(backend_root).resolve() / ".skills").resolve()
        if dest.exists() and dest.is_dir():
            return
        dest.mkdir(parents=True, exist_ok=True)

        reserved: set[str] = set()
        if os.name == "nt":
            reserved = {
                "con",
                "prn",
                "aux",
                "nul",
                *(f"com{i}" for i in range(1, 10)),
                *(f"lpt{i}" for i in range(1, 10)),
            }

        def _ignore(_: str, names: list[str]) -> set[str]:
            if not reserved:
                return set()
            return {n for n in names if n.lower() in reserved}

        for child in src.iterdir():
            if child.is_dir():
                shutil.copytree(child, dest / child.name, dirs_exist_ok=True, ignore=_ignore)

    def _normalize_run_config(self, config: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in config.items():
            if not isinstance(k, str):
                continue
            kk = k.strip()
            if not kk:
                continue
            if kk == "thread-id":
                out["thread_id"] = v
                continue
            if kk == "recursion-limit":
                out["recursion_limit"] = v
                continue
            if kk == "no-stream":
                out["no_stream"] = v
                continue
            if kk == "backend-root":
                out["backend_root"] = v
                continue
            if kk in {"model-timeout", "model_timeout"}:
                out["model_timeout_seconds"] = v
                continue
            if kk in {"heartbeat-seconds", "heartbeat_seconds"}:
                out["heartbeat_seconds"] = v
                continue
            if kk in {"command-timeout", "command_timeout"}:
                out["command_timeout_seconds"] = v
                continue
            if kk in {"command-poll-seconds", "command_poll_seconds"}:
                out["command_poll_seconds"] = v
                continue
            if kk in {"command-idle-seconds", "command_idle_seconds"}:
                out["command_idle_seconds"] = v
                continue
            out[kk] = v
        return out

    def _normalize_backend_root(self, value: str) -> str | None:
        if not value:
            return None
        try:
            p = Path(value)
            if not p.is_absolute():
                p = (self._workspace_root() / p).resolve()
            else:
                p = p.resolve()

            base = self._workspace_root().resolve()
            if not p.is_relative_to(base):
                return None
            return str(p)
        except Exception:
            return None

    async def _persist_uploads(self, task_id: str, backend_root: str, files: list[UploadFile]) -> list[dict[str, Any]]:
        allowed_suffixes = {".pdb", ".xyz", ".md", ".txt", ".docx", ".doc"}
        max_bytes = 50 * 1024 * 1024
        backend = Path(backend_root)

        stored: list[dict[str, Any]] = []
        for f in files:
            original_name = f.filename or "upload.bin"
            suffix = Path(original_name).suffix.lower()
            if suffix not in allowed_suffixes:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unsupported file type: {suffix or '(no extension)'}",
                )

            stored_name = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}{suffix}"
            target = (backend / stored_name).resolve()
            if not target.is_relative_to(backend.resolve()):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid upload filename")

            def _copy_with_limit() -> int:
                written = 0
                with target.open("wb") as out:
                    while True:
                        chunk = f.file.read(1024 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > max_bytes:
                            raise ValueError("File too large")
                        out.write(chunk)
                return written

            try:
                size = await asyncio.to_thread(_copy_with_limit)
            except ValueError:
                try:
                    await asyncio.to_thread(target.unlink, missing_ok=True)
                except Exception:
                    pass
                raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="File too large")

            stored.append(
                {
                    "stored_path": str(target),
                    "virtual_path": f"/{target.relative_to(backend.resolve()).as_posix()}",
                    "original_filename": original_name,
                    "content_type": f.content_type,
                    "size": size,
                }
            )

        return stored

    async def _enrich_task(self, task: dict[str, Any], running_hint: bool) -> dict[str, Any]:
        config = task.get("config")
        backend_root: str | None = None
        if isinstance(config, dict):
            backend_root_value = config.get("backend_root")
            if isinstance(backend_root_value, str) and backend_root_value.strip():
                backend_root = backend_root_value.strip()
        task_id = str(task.get("task_id") or "").strip()
        default_root: str | None = None
        if task_id:
            default_root = str((self._workspace_root() / task_id).resolve())

        normalized_root: str | None = None
        if isinstance(backend_root, str) and backend_root:
            normalized_root = self._normalize_backend_root(backend_root)

        if normalized_root is None and default_root:
            normalized_root = default_root

        if normalized_root and default_root:
            try:
                normalized_path = Path(normalized_root).resolve()
                default_path = Path(default_root).resolve()
                if normalized_path != default_path and not normalized_path.is_relative_to(default_path):
                    normalized_root = default_root
            except Exception:
                normalized_root = default_root

        task["backend_root"] = normalized_root
        task["agent_running"] = running_hint

        result = task.get("result")
        if isinstance(result, dict):
            ai_message_value = result.get("ai_message")
            if not isinstance(ai_message_value, (list, dict)):
                ai_message_value = []

            legacy_message = None
            message_value = result.get("message")
            if isinstance(message_value, str) and message_value:
                legacy_message = message_value
            else:
                legacy_content = result.get("content")
                if isinstance(legacy_content, str) and legacy_content:
                    legacy_message = legacy_content

            if isinstance(ai_message_value, list):
                if legacy_message is not None and not ai_message_value:
                    ai_message_value.append(legacy_message)
                result["ai_message"] = ai_message_value
            else:
                result["ai_message"] = ai_message_value

            if "message" in result:
                result.pop("message", None)
            if "content" in result:
                result.pop("content", None)
            task["result"] = result

        now = datetime.now(timezone.utc)
        start_dt: datetime | None = None
        if isinstance(config, dict):
            started_at = config.get("processing_started_at")
            if isinstance(started_at, str) and started_at:
                try:
                    start_dt = datetime.fromisoformat(started_at)
                except Exception:
                    start_dt = None
        if start_dt is None:
            created_at = task.get("created_at")
            if isinstance(created_at, datetime):
                start_dt = created_at

        duration_seconds: int | None = None
        status_value = task.get("status")
        if status_value in {TaskStatus.PROCESSING, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED} and isinstance(start_dt, datetime):
            completed_at = task.get("completed_at")
            end_dt: datetime = completed_at if isinstance(completed_at, datetime) else now
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            if isinstance(end_dt, datetime) and end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            try:
                duration_seconds = int(max(0.0, (end_dt - start_dt).total_seconds()))
            except Exception:
                duration_seconds = None
        task["estimated_remaining_seconds"] = duration_seconds

        if isinstance(normalized_root, str) and normalized_root:
            task["backend_files"] = await asyncio.to_thread(self._scan_backend_files, normalized_root)
        else:
            task["backend_files"] = []
        return task

    def _scan_backend_files(self, backend_root: str) -> list[dict[str, Any]]:
        root = Path(backend_root)
        if not root.exists() or not root.is_dir():
            return []

        max_entries = 500
        max_depth = 5
        out: list[dict[str, Any]] = []
        stack: list[tuple[Path, int]] = [(root, 0)]

        while stack and len(out) < max_entries:
            current, depth = stack.pop()
            try:
                for entry in current.iterdir():
                    if len(out) >= max_entries:
                        break
                    if entry.name in {".skills", ".deepagents"}:
                        continue
                    try:
                        rel = str(entry.relative_to(root))
                    except Exception:
                        rel = str(entry)

                    is_dir = False
                    try:
                        is_dir = entry.is_dir()
                    except Exception:
                        is_dir = False

                    size: int | None = None
                    mtime: str | None = None
                    try:
                        stat = entry.stat()
                        if not is_dir:
                            size = int(stat.st_size)
                        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
                    except Exception:
                        pass

                    out.append(
                        {
                            "path": rel,
                            "is_dir": is_dir,
                            "size": size,
                            "modified_at": mtime,
                        }
                    )
                    if is_dir and depth < max_depth:
                        stack.append((entry, depth + 1))
            except Exception:
                continue

        out.sort(key=lambda x: str(x.get("path") or ""))
        return out

    async def _run_dummy(self, task_id: str, data: Any, config: dict[str, Any]) -> dict[str, Any]:
        await self._task_repo.update(task_id, progress=10)
        await asyncio.sleep(0.5)
        await self._task_repo.update(task_id, progress=40)
        await asyncio.sleep(0.5)
        await self._task_repo.update(task_id, progress=80)
        await asyncio.sleep(0.5)
        return {"echo": data, "config": config}

    async def _run_deepagent(self, task_id: str, data: Any, config: dict[str, Any]) -> dict[str, Any]:
        if not self._can_run_deepagent():
            raise RuntimeError("Missing OPENAI_API_KEY / OPENAI_API_MODEL environment variables.")

        import inspect

        from services.agents.agent import build_agent

        task_backend_root = config.get("backend_root")
        if not isinstance(task_backend_root, str) or not task_backend_root.strip():
            task_backend_root = str((self._workspace_root() / task_id).resolve())
        else:
            normalized = self._normalize_backend_root(task_backend_root.strip())
            if normalized is None:
                raise RuntimeError("Invalid backend_root")
            task_backend_root = normalized

        Path(task_backend_root).mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._ensure_task_skills_dir, task_backend_root)
        workspace_root = str(self._workspace_root().resolve())

        recursion_limit = config.get("recursion_limit", config.get("recursion-limit"))
        if isinstance(recursion_limit, str) and recursion_limit.strip().isdigit():
            recursion_limit = int(recursion_limit.strip())
        if not isinstance(recursion_limit, int) or recursion_limit <= 0:
            recursion_limit = 512

        thread_id = config.get("thread_id", config.get("thread-id"))
        if not isinstance(thread_id, str) or not thread_id.strip():
            configurable = config.get("configurable")
            if isinstance(configurable, dict):
                thread_id = configurable.get("thread_id", configurable.get("thread-id"))
        if not isinstance(thread_id, str) or not thread_id.strip():
            thread_id = task_id

        messages = self._normalize_messages(data)
        files = self._extract_files(data)
        if files:
            messages = self._append_files_hint(messages, files)

        settings = get_settings()
        model_timeout = config.get("model_timeout_seconds")
        if isinstance(model_timeout, str) and model_timeout.strip().isdigit():
            model_timeout = int(model_timeout.strip())
        if not isinstance(model_timeout, int) or model_timeout <= 0:
            model_timeout = settings.agent_timeout_seconds

        heartbeat_seconds = config.get("heartbeat_seconds")
        if isinstance(heartbeat_seconds, str) and heartbeat_seconds.strip().isdigit():
            heartbeat_seconds = int(heartbeat_seconds.strip())
        if not isinstance(heartbeat_seconds, int) or heartbeat_seconds <= 0:
            heartbeat_seconds = settings.agent_heartbeat_seconds

        agent = build_agent(
            backend_root=task_backend_root,
            workspace_root=workspace_root,
            model_timeout=model_timeout,
        )
        invoke_config = {"recursion_limit": recursion_limit, "configurable": {"thread_id": thread_id}}
        payload = {"messages": messages}

        ai_message: list[str] = []
        await self._task_repo.update(task_id, progress=15, result={"ai_message": list(ai_message), "final": False})

        done = asyncio.Event()

        async def _heartbeat_loop() -> None:
            while not done.is_set():
                await asyncio.sleep(heartbeat_seconds)
                now = datetime.now(timezone.utc).isoformat()
                config["last_heartbeat_at"] = now
                await self._task_repo.update(
                    task_id,
                    config=config,
                    result={"ai_message": list(ai_message), "final": False, "heartbeat_at": now, "runner_status": "running"},
                )

        heartbeat_task = asyncio.create_task(_heartbeat_loop())

        def _extract_content(obj: Any) -> str | None:
            if isinstance(obj, dict):
                messages_value = obj.get("messages")
                if isinstance(messages_value, list) and messages_value:
                    last_msg = messages_value[-1]
                    if isinstance(last_msg, dict):
                        content_value = last_msg.get("content")
                        if isinstance(content_value, str):
                            return content_value
                    content_value = getattr(last_msg, "content", None)
                    if isinstance(content_value, str):
                        return content_value
            return None

        async def _invoke_streaming() -> str:
            if not hasattr(agent, "astream") or not callable(getattr(agent, "astream")):
                return await _invoke_once()

            params = {}
            try:
                params = dict(inspect.signature(agent.astream).parameters)
            except Exception:
                params = {}

            stream_kwargs: dict[str, Any] = {}
            if "stream_mode" in params:
                stream_kwargs["stream_mode"] = "values"

            content_value = ""
            updates = 0

            async for chunk in agent.astream(payload, config=invoke_config, **stream_kwargs):
                candidate = _extract_content(chunk)
                if not isinstance(candidate, str):
                    continue
                if candidate == content_value:
                    continue
                previous_value = content_value
                content_value = candidate

                updates += 1
                delta = content_value
                if isinstance(previous_value, str) and previous_value and isinstance(content_value, str):
                    if content_value.startswith(previous_value):
                        delta = content_value[len(previous_value):]
                if isinstance(delta, str) and delta:
                    ai_message.append(delta)
                await self._task_repo.update(
                    task_id,
                    progress=min(90, 15 + updates),
                    result={"ai_message": list(ai_message), "final": False},
                )

            return content_value

        async def _invoke_once() -> str:
            if hasattr(agent, "ainvoke") and callable(getattr(agent, "ainvoke")):
                result = await agent.ainvoke(payload, config=invoke_config)
            else:
                result = await anyio.to_thread.run_sync(lambda: agent.invoke(payload, config=invoke_config))
            last = result["messages"][-1]
            content = getattr(last, "content", None)
            if not isinstance(content, str):
                return ""
            return content

        try:
            content = await _invoke_streaming()
            if not ai_message and isinstance(content, str) and content:
                ai_message.append(content)
            await self._task_repo.update(task_id, progress=95, result={"ai_message": list(ai_message), "final": True})
            return {"ai_message": list(ai_message), "final": True, "files": files, "backend_root": task_backend_root, "thread_id": thread_id}
        finally:
            done.set()
            heartbeat_task.cancel()

    async def _run_command(self, task_id: str, data: Any, config: dict[str, Any]) -> dict[str, Any]:
        from services.agents.tools import exec_command, process

        settings = get_settings()
        command = config.get("command")
        if not isinstance(command, str) or not command.strip():
            if isinstance(data, dict):
                command = data.get("command")
        if not isinstance(command, str) or not command.strip():
            raise RuntimeError("command runner 缺少 command")

        timeout_value = config.get("command_timeout_seconds")
        if isinstance(timeout_value, str) and timeout_value.strip().isdigit():
            timeout_value = int(timeout_value.strip())
        if not isinstance(timeout_value, int) or timeout_value <= 0:
            timeout_value = settings.command_timeout_seconds

        poll_seconds = config.get("command_poll_seconds")
        if isinstance(poll_seconds, str) and poll_seconds.strip().isdigit():
            poll_seconds = int(poll_seconds.strip())
        if not isinstance(poll_seconds, int) or poll_seconds <= 0:
            poll_seconds = settings.command_poll_seconds

        idle_seconds = config.get("command_idle_seconds")
        if isinstance(idle_seconds, str) and idle_seconds.strip().isdigit():
            idle_seconds = int(idle_seconds.strip())
        if not isinstance(idle_seconds, int) or idle_seconds <= 0:
            idle_seconds = settings.command_idle_seconds

        backend_root = config.get("backend_root")
        if not isinstance(backend_root, str) or not backend_root.strip():
            backend_root = str((self._workspace_root() / task_id).resolve())

        os.environ["DEEPAGENT_BACKEND_ROOT"] = backend_root
        exec_result = exec_command(
            command=command.strip(),
            yieldMs=10000,
            background=True,
            timeout=int(timeout_value),
            cwd=".",
        )
        if not exec_result.get("ok"):
            return {
                "__task_status": TaskStatus.FAILED,
                "__task_error": {"message": str(exec_result.get("error") or "命令启动失败")},
                "runner": "command",
                "command": command.strip(),
            }

        session_id = exec_result.get("sessionId")
        if not isinstance(session_id, str) or not session_id:
            return {
                "__task_status": TaskStatus.FAILED,
                "__task_error": {"message": "无法获取后台会话 ID"},
                "runner": "command",
                "command": command.strip(),
            }

        await self._task_repo.update(
            task_id,
            progress=10,
            result={"runner": "command", "session_id": session_id, "status": "running", "command": command.strip()},
        )

        stdout_tail = ""
        last_output_at = datetime.now(timezone.utc)
        progress_value = 20
        while True:
            await asyncio.sleep(poll_seconds)
            status = process(action="poll", sessionId=session_id)
            if not status.get("ok"):
                return {
                    "__task_status": TaskStatus.FAILED,
                    "__task_error": {"message": str(status.get("error") or "后台会话查询失败")},
                    "runner": "command",
                    "command": command.strip(),
                    "session_id": session_id,
                }

            output = status.get("output")
            if isinstance(output, str) and output.strip():
                stdout_tail = output.strip()[-4000:]
                last_output_at = datetime.now(timezone.utc)

            state = status.get("status")
            exit_code = status.get("exitCode")
            runner_state = state
            idle_elapsed = (datetime.now(timezone.utc) - last_output_at).total_seconds()
            if state == "running" and idle_seconds and idle_elapsed >= idle_seconds:
                runner_state = "paused"
            progress_value = min(95, progress_value + 1)
            await self._task_repo.update(
                task_id,
                progress=progress_value,
                result={
                    "runner": "command",
                    "session_id": session_id,
                    "status": runner_state,
                    "command": command.strip(),
                    "stdout_tail": stdout_tail,
                },
            )

            if state == "completed":
                if isinstance(exit_code, int) and exit_code != 0:
                    return {
                        "__task_status": TaskStatus.FAILED,
                        "__task_error": {"message": f"命令退出码 {exit_code}"},
                        "runner": "command",
                        "session_id": session_id,
                        "command": command.strip(),
                        "stdout_tail": stdout_tail,
                        "exit_code": exit_code,
                    }
                return {
                    "__task_status": TaskStatus.COMPLETED,
                    "runner": "command",
                    "session_id": session_id,
                    "command": command.strip(),
                    "stdout_tail": stdout_tail,
                    "exit_code": exit_code,
                }

    def _normalize_messages(self, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            msgs = data.get("messages")
            if isinstance(msgs, list) and msgs:
                out: list[dict[str, Any]] = []
                for m in msgs:
                    if not isinstance(m, dict):
                        continue
                    role = m.get("role")
                    content = m.get("content")
                    if isinstance(role, str) and isinstance(content, str) and role and content:
                        out.append({"role": role, "content": content})
                if out:
                    return out

            content = data.get("content")
            if isinstance(content, str) and content.strip():
                return [{"role": "user", "content": content.strip()}]

            message = data.get("message")
            if isinstance(message, str) and message.strip():
                return [{"role": "user", "content": message.strip()}]

        if isinstance(data, str) and data.strip():
            return [{"role": "user", "content": data.strip()}]

        return [{"role": "user", "content": ""}]

    def _extract_files(self, data: Any) -> list[str]:
        if not isinstance(data, dict):
            return []
        files = data.get("files")
        if isinstance(files, list):
            out: list[str] = []
            for f in files:
                if isinstance(f, str) and f:
                    out.append(f)
                elif isinstance(f, dict):
                    virtual_path = f.get("virtual_path")
                    if isinstance(virtual_path, str) and virtual_path:
                        out.append(virtual_path)
                    else:
                        stored_path = f.get("stored_path")
                        if isinstance(stored_path, str) and stored_path:
                            out.append(stored_path)
                        else:
                            path = f.get("path")
                            if isinstance(path, str) and path:
                                out.append(path)
            return out
        return []

    def _append_files_hint(self, messages: list[dict[str, Any]], files: list[str]) -> list[dict[str, Any]]:
        if not messages:
            messages = [{"role": "user", "content": ""}]
        last = messages[-1]
        content = last.get("content")
        if not isinstance(content, str):
            content = ""
        hint = "\n\n已上传文件路径：\n" + "\n".join([f"- {p}" for p in files])
        messages[-1] = {"role": str(last.get("role") or "user"), "content": content + hint}
        return messages
