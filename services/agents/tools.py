from __future__ import annotations

import os
import platform
import queue
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

try:
    from langchain_core.tools import StructuredTool
except Exception:  # pragma: no cover
    StructuredTool = None  # type: ignore[assignment]

def get_system_time(utc: bool = False) -> str:
    """Get current system time."""
    now = datetime.now(timezone.utc) if utc else datetime.now().astimezone()
    return now.isoformat()


def _workspace_cwd() -> str:
    configured = os.getenv("DEEPAGENT_BACKEND_ROOT")
    if configured:
        return str(Path(configured).expanduser().resolve())
    return str(Path(__file__).resolve().parents[1])

def _resolve_exec_cwd(requested: str | None) -> tuple[str | None, str | None]:
    default_cwd = Path(_workspace_cwd()).expanduser().resolve()
    workspace_root = default_cwd.parent

    if requested is None:
        return str(default_cwd), None
    requested = str(requested).strip()
    if not requested:
        return str(default_cwd), None

    try:
        p = Path(requested).expanduser()
        resolved = p.resolve() if p.is_absolute() else (default_cwd / p).resolve()
    except Exception as e:
        return None, f"cwd 无效：{e}"

    if resolved != workspace_root and not resolved.is_relative_to(workspace_root):
        return None, f"cwd 超出允许范围：{workspace_root}"
    if not resolved.exists() or not resolved.is_dir():
        return None, f"cwd 不存在或不是目录：{resolved}"

    return str(resolved), None


@dataclass
class _ProcSession:
    session_id: str
    command: str
    cwd: str
    created_at: float
    timeout_s: int
    pty: bool
    host: str
    elevated: bool
    process: subprocess.Popen[str]
    stdin_queue: "queue.Queue[str]" = field(default_factory=queue.Queue)
    output_lines: list[str] = field(default_factory=list)
    delta_cursor: int = 0
    exit_code: int | None = None
    ended_at: float | None = None
    killed: bool = False
    last_error: str | None = None


_SESSIONS_LOCK = threading.RLock()
_SESSIONS: dict[str, _ProcSession] = {}


def _is_windows() -> bool:
    return platform.system().lower().startswith("win")


def _powershell_command(command: str) -> list[str]:
    return ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]


def _kill_process_tree(proc: subprocess.Popen[str]) -> tuple[bool, str | None]:
    if proc.poll() is not None:
        return True, None

    try:
        if _is_windows():
            completed = subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                text=True,
            )
            return completed.returncode == 0, (completed.stderr or completed.stdout or None)
        killpg = getattr(os, "killpg", None)
        getpgid = getattr(os, "getpgid", None)
        sigkill = getattr(signal, "SIGKILL", None)
        try:
            if callable(killpg) and callable(getpgid) and sigkill is not None:
                killpg(getpgid(proc.pid), sigkill)
                return True, None
            proc.kill()
            return True, None
        except Exception:
            proc.kill()
            return True, None
    except Exception as e:  # pragma: no cover
        return False, str(e)


def _append_output(session: _ProcSession, text: str) -> None:
    if not text:
        return
    for line in text.splitlines():
        session.output_lines.append(line)


def _pipe_reader_thread(session: _ProcSession, stream: Any) -> None:
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            with _SESSIONS_LOCK:
                _append_output(session, line.rstrip("\n"))
    except Exception as e:  # pragma: no cover
        with _SESSIONS_LOCK:
            session.last_error = str(e)


def _waiter_thread(session: _ProcSession) -> None:
    try:
        rc = session.process.wait()
        with _SESSIONS_LOCK:
            session.exit_code = rc
            session.ended_at = session.ended_at or time.time()
    except Exception as e:  # pragma: no cover
        with _SESSIONS_LOCK:
            session.last_error = str(e)


def _stdin_writer_thread(session: _ProcSession) -> None:
    proc = session.process
    if proc.stdin is None:
        return
    try:
        while proc.poll() is None:
            try:
                chunk = session.stdin_queue.get(timeout=0.1)
            except queue.Empty:
                continue
            proc.stdin.write(chunk)
            proc.stdin.flush()
    except Exception as e:  # pragma: no cover
        with _SESSIONS_LOCK:
            session.last_error = str(e)


def _timeout_thread(session: _ProcSession) -> None:
    deadline = session.created_at + session.timeout_s
    while True:
        time.sleep(0.25)
        with _SESSIONS_LOCK:
            proc = session.process
            if session.exit_code is not None or proc.poll() is not None:
                session.exit_code = proc.returncode
                session.ended_at = session.ended_at or time.time()
                return
            if time.time() >= deadline:
                ok, err = _kill_process_tree(proc)
                session.killed = True
                session.last_error = err
                session.exit_code = proc.poll()
                session.ended_at = time.time()
                return


def _ensure_elevated_allowed(elevated: bool) -> tuple[bool, str | None]:
    if not elevated:
        return True, None
    allow_tools = os.getenv("DEEPAGENT_TOOLS_ELEVATED", "").strip() in {"1", "true", "True", "yes", "YES"}
    allow_agent = os.getenv("DEEPAGENT_AGENT_ELEVATED", "").strip() in {"1", "true", "True", "yes", "YES"}
    if allow_tools and allow_agent:
        return True, None
    return False, "elevated 未启用：需要同时设置 DEEPAGENT_TOOLS_ELEVATED=1 与 DEEPAGENT_AGENT_ELEVATED=1"


def exec_command(
    command: str,
    yieldMs: int = 10000,
    background: bool = False,
    timeout: int = 1800,
    pty: bool = False,
    host: str = "local",
    elevated: bool = False,
    cwd: str | None = None,
) -> dict[str, Any]:
    ok, err = _ensure_elevated_allowed(elevated)
    if not ok:
        return {"ok": False, "error": err}

    if host not in {"local", "node"}:
        return {"ok": False, "error": f"不支持的 host: {host}"}
    if host == "node":
        return {"ok": False, "error": "host=node 暂未实现"}

    resolved_cwd, cwd_err = _resolve_exec_cwd(cwd)
    if cwd_err is not None or resolved_cwd is None:
        return {"ok": False, "error": cwd_err or "cwd 无效"}
    cwd = resolved_cwd
    session_id = uuid.uuid4().hex[:12]

    stdout_setting: int | None = subprocess.PIPE
    stderr_setting: int | None = subprocess.PIPE

    if pty and not _is_windows():
        stdout_setting = subprocess.PIPE
        stderr_setting = subprocess.STDOUT
    elif pty and _is_windows():
        pty = False

    creationflags = 0
    preexec_fn = None
    if _is_windows():
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        preexec_fn = getattr(os, "setsid", None)

    proc = subprocess.Popen(
        _powershell_command(command) if _is_windows() else command,
        shell=not _is_windows(),
        cwd=cwd,
        stdin=subprocess.PIPE,
        stdout=stdout_setting,
        stderr=stderr_setting,
        text=True,
        bufsize=1,
        creationflags=creationflags,
        preexec_fn=preexec_fn,
    )

    session = _ProcSession(
        session_id=session_id,
        command=command,
        cwd=cwd,
        created_at=time.time(),
        timeout_s=max(int(timeout), 1),
        pty=pty,
        host=host,
        elevated=elevated,
        process=proc,
    )

    with _SESSIONS_LOCK:
        _SESSIONS[session_id] = session

    if proc.stdout is not None:
        threading.Thread(target=_pipe_reader_thread, args=(session, proc.stdout), daemon=True).start()
    if proc.stderr is not None and proc.stderr is not subprocess.STDOUT:
        threading.Thread(target=_pipe_reader_thread, args=(session, proc.stderr), daemon=True).start()
    threading.Thread(target=_waiter_thread, args=(session,), daemon=True).start()
    threading.Thread(target=_stdin_writer_thread, args=(session,), daemon=True).start()
    threading.Thread(target=_timeout_thread, args=(session,), daemon=True).start()

    if background:
        return {"ok": True, "status": "running", "sessionId": session_id, "cwd": cwd}

    deadline = time.time() + max(yieldMs, 0) / 1000.0
    while time.time() < deadline:
        if proc.poll() is not None:
            break
        time.sleep(0.02)

    with _SESSIONS_LOCK:
        output = "\n".join(session.output_lines)
        if proc.poll() is None:
            return {
                "ok": True,
                "status": "running",
                "sessionId": session_id,
                "cwd": cwd,
                "output": output,
            }
        session.exit_code = proc.returncode
        session.ended_at = session.ended_at or time.time()
        return {
            "ok": True,
            "status": "completed",
            "sessionId": session_id,
            "cwd": cwd,
            "exitCode": session.exit_code,
            "output": output,
        }


def process(
    action: Literal[
        "list",
        "poll",
        "log",
        "write",
        "kill",
        "clear",
        "remove",
    ],
    sessionId: str | None = None,
    text: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    with _SESSIONS_LOCK:
        if action == "list":
            items = []
            for s in _SESSIONS.values():
                status = "running" if s.process.poll() is None and s.exit_code is None else "completed"
                items.append(
                    {
                        "sessionId": s.session_id,
                        "command": s.command,
                        "cwd": s.cwd,
                        "status": status,
                        "exitCode": s.exit_code,
                        "createdAt": s.created_at,
                        "endedAt": s.ended_at,
                        "killed": s.killed,
                        "pty": s.pty,
                        "host": s.host,
                        "elevated": s.elevated,
                        "lastError": s.last_error,
                    }
                )
            items.sort(key=lambda x: float(x.get("createdAt") or 0.0), reverse=True)
            return {"ok": True, "sessions": items}

        if not sessionId:
            return {"ok": False, "error": "sessionId 必填"}
        session = _SESSIONS.get(sessionId)
        if not session:
            return {"ok": False, "error": f"未知 sessionId: {sessionId}"}

        proc = session.process
        if proc.poll() is not None and session.exit_code is None:
            session.exit_code = proc.returncode
            session.ended_at = session.ended_at or time.time()

        if action == "poll":
            total = len(session.output_lines)
            new_lines = session.output_lines[session.delta_cursor : total]
            session.delta_cursor = total
            status = "running" if proc.poll() is None and session.exit_code is None else "completed"
            return {
                "ok": True,
                "status": status,
                "sessionId": session.session_id,
                "exitCode": session.exit_code,
                "output": "\n".join(new_lines),
            }

        if action == "log":
            total = len(session.output_lines)
            if offset < 0:
                start = max(total + offset, 0)
            else:
                start = min(offset, total)
            end = min(start + max(limit, 0), total)
            return {
                "ok": True,
                "sessionId": session.session_id,
                "totalLines": total,
                "offset": start,
                "limit": limit,
                "output": "\n".join(session.output_lines[start:end]),
            }

        if action == "write":
            if text is None:
                return {"ok": False, "error": "write 需要 text"}
            if proc.poll() is not None:
                return {"ok": False, "error": "进程已结束，无法写入"}
            session.stdin_queue.put(text)
            return {"ok": True, "sessionId": session.session_id}

        if action == "kill":
            ok, err = _kill_process_tree(proc)
            session.killed = True
            session.last_error = err or session.last_error
            session.exit_code = proc.poll()
            session.ended_at = session.ended_at or time.time()
            return {"ok": ok, "sessionId": session.session_id, "exitCode": session.exit_code, "error": err}

        if action == "clear":
            session.output_lines.clear()
            session.delta_cursor = 0
            return {"ok": True, "sessionId": session.session_id}

        if action == "remove":
            if proc.poll() is None and session.exit_code is None:
                return {"ok": False, "error": "会话仍在运行，请先 kill"}
            _SESSIONS.pop(session.session_id, None)
            return {"ok": True, "sessionId": session.session_id}

        return {"ok": False, "error": f"不支持的 action: {action}"}


def build_tools() -> list[Any]:
    if StructuredTool is None:
        return [get_system_time, exec_command, process]

    exec_tool = StructuredTool.from_function(
        func=exec_command,
        name="exec",
        description="""
        在工作区执行 shell 命令；支持 yieldMs/background/timeout/pty。
        核心参数：
        - command: 命令（必填）
        - cwd: 工作目录（可选；必须在 workspace 目录内）
        - yieldMs: 运行超过该毫秒数则转为后台（默认 10000）
        - background: 立即转后台（默认 false）
        - timeout: 秒数，超过则终止进程（默认 1800）
        - pty: 需要 TTY 时设置 true（Windows 会自动降级为普通管道）
        返回：
        - 前台完成：status=completed, exitCode, output
        - 转后台：status=running, sessionId, output(已产生的部分)
        注意：
        - Windows PowerShell不支持`&&`操作符
        """,
    )
    proc_tool = StructuredTool.from_function(
        func=process,
        name="process",
        description="""
        管理后台执行会话：list/poll/log/write/kill/clear/remove。
        核心参数：
        - action: list/poll/log/write/kill/clear/remove
        - sessionId: 除 list 外必填
        说明：
        - poll: 返回从上次 poll 以来新增的 output，以及完成状态/exitCode
        - log: 支持基于行的 offset/limit；offset<0 表示从末尾倒数
        """
    )
    return [get_system_time, exec_tool, proc_tool]
