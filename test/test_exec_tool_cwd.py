from services.agents.tools import exec_command


def test_exec_command_defaults_to_backend_root(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    task_dir = workspace / "tsk_abc"
    task_dir.mkdir(parents=True)

    monkeypatch.setenv("DEEPAGENT_BACKEND_ROOT", str(task_dir))
    result = exec_command('python -c "import os; print(os.getcwd())"')
    assert result["ok"] is True
    assert result["status"] == "completed"
    assert str(task_dir.resolve()) == str(result["cwd"])
    assert str(task_dir.resolve()) in str(result.get("output") or "")


def test_exec_command_allows_cwd_within_workspace(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    task_dir = workspace / "tsk_abc"
    task_dir.mkdir(parents=True)

    monkeypatch.setenv("DEEPAGENT_BACKEND_ROOT", str(task_dir))
    result = exec_command('python -c "import os; print(os.getcwd())"', cwd="..")
    assert result["ok"] is True
    assert result["status"] == "completed"
    assert str(workspace.resolve()) == str(result["cwd"])
    assert str(workspace.resolve()) in str(result.get("output") or "")


def test_exec_command_rejects_cwd_outside_workspace(tmp_path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    task_dir = workspace / "tsk_abc"
    task_dir.mkdir(parents=True)

    monkeypatch.setenv("DEEPAGENT_BACKEND_ROOT", str(task_dir))
    result = exec_command("python -V", cwd="../..")
    assert result["ok"] is False
