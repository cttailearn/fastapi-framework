import argparse
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

from services.agents.agent import build_agent


def _token_text_chunks(token: Any) -> Iterable[str]:
    blocks = getattr(token, "content_blocks", None)
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "text":
                continue
            text = block.get("text")
            if isinstance(text, str) and text:
                yield text
        return

    content = getattr(token, "content", None)
    if isinstance(content, str) and content:
        yield content


def _stream_text(agent: Any, payload: dict[str, Any], config: dict[str, Any]) -> Iterable[str]:
    stream = None
    try:
        stream = agent.stream(payload, config=config, stream_mode="messages")
    except TypeError:
        try:
            stream = agent.stream(payload, config=config, stream_mode=["messages"])
        except TypeError:
            stream = agent.stream(payload, config=config)

    for item in stream:
        if isinstance(item, tuple) and len(item) == 2:
            token, metadata = item
            node = None
            if isinstance(metadata, dict):
                node = metadata.get("langgraph_node")
            if node is not None and node != "model":
                continue
            yield from _token_text_chunks(token)
            continue

        if isinstance(item, dict):
            messages = item.get("messages")
            if isinstance(messages, list) and messages:
                last = messages[-1]
                content = getattr(last, "content", None)
                if isinstance(content, str) and content:
                    yield content
            continue


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="deepagent-framework")
    parser.add_argument("message", nargs="?", help="用户输入；省略则从 stdin 读取")
    parser.add_argument("--backend-root", default=None, help="FilesystemBackend 根目录（默认当前项目）")
    parser.add_argument("--thread-id", default=None, help="会话 thread_id（用于 checkpointer）")
    parser.add_argument("--recursion-limit", type=int, default=512)
    parser.add_argument("--no-stream", action="store_true", help="禁用流式输出")
    args = parser.parse_args(argv)

    message = args.message
    if message is None:
        message = sys.stdin.read().strip()
    if not message:
        return 2

    thread_id = args.thread_id or uuid.uuid4().hex
    config = {"recursion_limit": args.recursion_limit, "configurable": {"thread_id": thread_id}}

    backend_root = args.backend_root or str(Path(__file__).resolve().parent)
    agent = build_agent(backend_root=backend_root)
    payload = {"messages": [{"role": "user", "content": message}]}

    if args.no_stream:
        result = agent.invoke(payload, config=config)
        sys.stdout.write(result["messages"][-1].content)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0

    try:
        for chunk in _stream_text(agent, payload, config):
            sys.stdout.write(chunk)
            sys.stdout.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0
    except Exception:
        result = agent.invoke(payload, config=config)
        sys.stdout.write(result["messages"][-1].content)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
