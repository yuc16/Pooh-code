from __future__ import annotations

from dataclasses import dataclass

from .agent import PoohAgent


@dataclass
class CommandResult:
    handled: bool
    text: str = ""
    session_key: str | None = None


class CommandProcessor:
    def __init__(self, agent: PoohAgent) -> None:
        self.agent = agent

    def handle(self, raw: str, session_key: str) -> CommandResult:
        if not raw.startswith("/"):
            return CommandResult(False)
        parts = raw.strip().split(maxsplit=1)
        command = parts[0]
        argument = parts[1] if len(parts) > 1 else ""

        if command == "/help":
            return CommandResult(
                True,
                "/help /clear /compact /ctx /sessions /skills /prompt /model [name] /subagent <task> /exit",
            )
        if command == "/clear":
            new_session_id = self.agent.sessions.clear_session(session_key)
            return CommandResult(True, f"cleared session; new_session_id={new_session_id}")
        if command == "/compact":
            compacted = self.agent.compact_session(session_key, force=True)
            return CommandResult(True, "context compacted" if compacted else "nothing to compact")
        if command == "/ctx":
            usage = self.agent.get_context_usage(session_key)
            raw_usage = self.agent.sessions.get_last_usage(session_key)
            if isinstance(raw_usage, dict):
                input_tokens = raw_usage.get("input_tokens")
                output_tokens = raw_usage.get("output_tokens")
                total_tokens = raw_usage.get("total_tokens")
                return CommandResult(
                    True,
                    "上下文: "
                    f"{usage.display}\n"
                    f"input_tokens={input_tokens}  "
                    f"output_tokens={output_tokens}  "
                    f"total_tokens={total_tokens}\n"
                    f"auto_compact={usage.auto_compact_threshold}  "
                    f"blocking={usage.blocking_limit}",
                )
            return CommandResult(
                True,
                "上下文: "
                f"{usage.display}\n"
                "input_tokens=unknown  output_tokens=unknown  total_tokens=unknown\n"
                f"auto_compact={usage.auto_compact_threshold}  "
                f"blocking={usage.blocking_limit}",
            )
        if command == "/sessions":
            rows = []
            for item in self.agent.sessions.list_sessions()[:20]:
                rows.append(
                    f"{item['session_id']}  {item['session_key']}  messages={item['message_count']}"
                )
            return CommandResult(True, "\n".join(rows) or "(no sessions)")
        if command == "/skills":
            names = self.agent.skills.list_names()
            return CommandResult(True, "\n".join(names) or "(no skills)")
        if command == "/prompt":
            return CommandResult(True, self.agent.build_system_prompt(""))
        if command == "/model":
            if argument:
                self.agent.config.model = argument.strip()
                return CommandResult(True, f"model set to {self.agent.config.model}")
            return CommandResult(True, self.agent.config.model)
        if command == "/subagent":
            if not argument:
                return CommandResult(True, "usage: /subagent <task>")
            result = self.agent.run_subagent(
                session_key,
                description="manual-subagent",
                prompt=argument,
                agent_type="explorer",
            )
            return CommandResult(True, result)
        if command == "/exit":
            return CommandResult(True, "__EXIT__")
        return CommandResult(True, f"unknown command: {command}")
