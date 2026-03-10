import os
import shutil
import inspect
from pathlib import Path
from core.config import get_settings
from .tools import build_tools
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.memory import MemorySaver
from dotenv import load_dotenv

load_dotenv()

skills_dir = os.path.join(os.path.dirname(__file__), "skills")



system_instructions = """
你是一个通用助手，帮助用户完成任务。

默认用中文回复；仅在用户要求或上下文需要时切换语言。
""".strip()

def _ensure_workspace_skills_dir(workspace_root: str) -> str | None:
    src = Path(skills_dir).resolve()

    if not src.exists() or not src.is_dir():
        return None

    dest = Path(workspace_root).resolve() / ".skills"
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
    return str(dest)

def build_agent(
    backend_root: str | None = None,
    workspace_root: str | None = None,
    model_timeout: int | None = None,
    max_retries: int | None = None,
):
    from langchain.chat_models import init_chat_model

    settings = get_settings()
    timeout_value = model_timeout if isinstance(model_timeout, int) and model_timeout > 0 else settings.agent_timeout_seconds
    retries_value = max_retries if isinstance(max_retries, int) and max_retries >= 0 else settings.agent_max_retries
    model = init_chat_model(
        model=os.getenv("OPENAI_API_MODEL"),
        api_key=os.getenv("OPENAI_API_KEY"),
        api_base=os.getenv("OPENAI_API_BASE"),
        temperature=0.7,
        max_retries=retries_value,
        timeout=timeout_value,
    )

    default_root = str(Path(__file__).resolve().parents[1])
    task_root = backend_root or default_root
    os.environ["DEEPAGENT_BACKEND_ROOT"] = task_root

    task_backend = FilesystemBackend(root_dir=task_root, virtual_mode=True)

    skills_root = _ensure_workspace_skills_dir(task_root)
    try:
        from deepagents import async_create_deep_agent
    except Exception:
        async_create_deep_agent = None

    create_fn = async_create_deep_agent or create_deep_agent
    supports_skills = "skills" in inspect.signature(create_fn).parameters

    backend = task_backend
    skills_sources = ["/.skills/"] if skills_root is not None and supports_skills else None

    return create_fn(
        backend=backend,
        skills=skills_sources,
        tools=build_tools(),
        model=model,
        system_prompt=system_instructions,
        checkpointer=MemorySaver(),
        
    )


if __name__ == "__main__":
    agent = build_agent()
    result = agent.invoke(
        {"messages": [{"role": "user", "content": "你可以执行命令吗？可以的话查看一下当前运行的系统"}]},
        config={"recursion_limit": 64, "configurable": {"thread_id": "default"}},
    )
    print(result["messages"][-1].content)
