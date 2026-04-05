from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
import threading

from .agent import PoohAgent
from .channels.cli import CLIChannel
from .channels.feishu_ws import FeishuWebSocketChannel
from .commands import CommandProcessor
from .config import load_settings
from .lane import LaneManager


def _run_cli(agent: PoohAgent) -> int:
    channel = CLIChannel()
    commands = CommandProcessor(agent)
    session_key = agent.build_session_key("cli", "local", "cli-user")
    while True:
        usage = agent.get_context_usage(session_key)
        prompt_text = f"[{usage.display}] You > "
        inbound = channel.receive(prompt_text=prompt_text)
        if inbound is None:
            break
        command = commands.handle(inbound.text, session_key)
        if command.handled:
            if command.text == "__EXIT__":
                break
            channel.send(inbound.peer_id, command.text)
            continue
        reply = agent.ask(session_key, inbound.text)
        usage_after = agent.get_context_usage(session_key)
        if reply.compacted:
            channel.send(
                inbound.peer_id,
                f"[autocompact -> {usage_after.display}]\n{reply.text}",
            )
            continue
        channel.send(inbound.peer_id, reply.text)
    return 0


def _run_feishu(agent: PoohAgent) -> int:
    lane_manager = LaneManager()
    channel = FeishuWebSocketChannel(agent.config.feishu)
    channel.start()
    try:
        while True:
            inbound = channel.receive(timeout=1.0)
            if inbound is None:
                continue
            session_key = agent.build_session_key(
                inbound.channel,
                inbound.account_id,
                inbound.peer_id,
            )

            def _handle() -> None:
                reply = agent.ask(session_key, inbound.text)
                channel.send(inbound.chat_id or inbound.peer_id, reply.text)

            lane_manager.enqueue(session_key, _handle)
            time.sleep(0.01)
    except KeyboardInterrupt:
        return 0
    finally:
        channel.close()


def _run_feishu_background(agent: PoohAgent) -> None:
    if not agent.config.feishu.enabled:
        return
    if not agent.config.feishu.app_id or not agent.config.feishu.app_secret:
        print("Feishu 未配置，跳过长连接。")
        return
    print("飞书长连接已在后台启动。")
    thread = threading.Thread(target=_run_feishu, args=(agent,), daemon=True, name="feishu-main")
    thread.start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pooh-code")
    parser.add_argument("--config", help="Path to settings.json", default=None)
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("serve", help="同时启动 CLI 和飞书长连接")
    subparsers.add_parser("chat", help="Start local CLI chat")
    subparsers.add_parser("feishu", help="Run Feishu websocket worker")
    subparsers.add_parser("sessions", help="List stored sessions")
    args = parser.parse_args(argv)

    settings = load_settings(path=Path(args.config) if args.config else None)
    agent = PoohAgent(settings)

    if args.command in {None, "serve"}:
        _run_feishu_background(agent)
        return _run_cli(agent)
    if args.command == "chat":
        return _run_cli(agent)
    if args.command == "feishu":
        if not settings.feishu.app_id or not settings.feishu.app_secret:
            print("Feishu app_id/app_secret missing in workplace/runtime/config/settings.json")
            return 1
        return _run_feishu(agent)
    if args.command == "sessions":
        for item in agent.sessions.list_sessions():
            print(
                f"{item['session_id']}  {item['session_key']}  messages={item['message_count']}  last_active={item['last_active']}"
            )
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
