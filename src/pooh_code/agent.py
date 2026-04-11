from __future__ import annotations

import json
import os
import threading
from typing import Any

from .config import AgentConfig
from .context import ContextManager, ContextUsage
from .models import AgentReply
from .openai_codex import PoohCodexClient
from .paths import BOOTSTRAP_FILES, PROJECT_ROOT, RUNTIME_DIR, ensure_runtime_dirs
from .session_store import SessionStore
from .skills import SkillsManager
from .subagent import (
    SubAgentRequest,
    build_subagent_prompt,
    build_subagent_session_key,
    build_subagent_system_prompt,
)
from .time_utils import SHANGHAI_TZ_NAME, shanghai_now_iso
from .tooling import ToolRegistry


class PoohAgent:
    def __init__(
        self,
        config: AgentConfig,
        *,
        agent_id: str = "main",
        readonly: bool = False,
        enable_subagents: bool = True,
        extra_system_prompt: str = "",
    ) -> None:
        ensure_runtime_dirs()
        self.config = config
        self.agent_id = agent_id
        self.readonly = readonly
        self.enable_subagents = enable_subagents
        self.extra_system_prompt = extra_system_prompt
        self.client = PoohCodexClient()
        self.context = ContextManager(
            self.client,
            self.config.model,
            context_window=self.config.context_window,
        )
        self.sessions = SessionStore(agent_id=agent_id)
        self.skills = SkillsManager()
        self._session_local = threading.local()
        self.tools = ToolRegistry(
            readonly=readonly,
            enable_subagents=enable_subagents,
            spawn_agent_callback=self._spawn_agent,
        )

    def build_session_key(
        self, channel: str, account_id: str, peer_id: str, agent_id: str | None = None
    ) -> str:
        actual_agent = agent_id or self.agent_id
        parts = [
            actual_agent,
            channel or "unknown",
            account_id or "default",
            peer_id or "main",
        ]
        return "agent:" + ":".join(parts)

    def build_system_prompt(self, user_text: str) -> str:
        parts = [self._load_bootstrap_files(), self.skills.render_for_prompt(user_text)]
        runtime = {
            "agent_name": self.config.name,
            "agent_id": self.agent_id,
            "readonly": self.readonly,
            "subagents_enabled": self.enable_subagents,
            "model": self.config.model,
            "project_root": str(PROJECT_ROOT),
            "runtime_root": str(RUNTIME_DIR),
            "cwd": os.getcwd(),
            "timezone": SHANGHAI_TZ_NAME,
            "local_time": shanghai_now_iso(),
        }
        parts.append("## Runtime\n" + json.dumps(runtime, ensure_ascii=False, indent=2))
        if self.extra_system_prompt.strip():
            parts.append("## Agent Policy\n" + self.extra_system_prompt.strip())
        return "\n\n".join(part for part in parts if part.strip())

    def _load_bootstrap_files(self) -> str:
        sections = []
        for name in BOOTSTRAP_FILES:
            path = RUNTIME_DIR / name
            if not path.exists():
                continue
            try:
                content = path.read_text(encoding="utf-8").strip()
            except Exception:
                continue
            if content:
                sections.append(f"## {name}\n{content}")
        return "\n\n".join(sections)

    def get_context_usage(
        self, session_key: str, pending_user_text: str = "", user_text_for_prompt: str = ""
    ) -> ContextUsage:
        self.context.model = self.config.model
        self.context.context_window = self.config.context_window
        if not pending_user_text:
            usage = self.sessions.get_last_usage(session_key)
            real_total_tokens = None
            if isinstance(usage, dict):
                raw = usage.get("total_tokens")
                if isinstance(raw, int):
                    real_total_tokens = raw
            return self.context.usage_from_real_tokens(real_total_tokens)
        messages = self.sessions.load_messages(session_key)
        if pending_user_text:
            messages = [*messages, {"role": "user", "content": pending_user_text}]
        return self.context.usage(messages, self.build_system_prompt(user_text_for_prompt))

    def _get_real_total_tokens(self, session_key: str) -> int | None:
        usage = self.sessions.get_last_usage(session_key)
        if isinstance(usage, dict):
            raw = usage.get("total_tokens")
            if isinstance(raw, int) and raw > 0:
                return raw
        return None

    def compact_session(
        self,
        session_key: str,
        *,
        user_text_for_prompt: str = "",
        force: bool = False,
    ) -> bool:
        self.context.model = self.config.model
        self.context.context_window = self.config.context_window
        messages = self.sessions.load_messages(session_key)
        if not messages:
            return False
        system_prompt = self.build_system_prompt(user_text_for_prompt)
        real_tokens = self._get_real_total_tokens(session_key)
        if not force and not self.context.should_compact(
            messages, system_prompt, real_total_tokens=real_tokens
        ):
            return False
        compacted = self.context.compact_messages(messages, system_prompt)
        if compacted == messages:
            return False
        self.sessions.replace_messages(session_key, compacted)
        self.sessions.invalidate_last_usage(session_key)
        return True

    def _spawn_agent(
        self,
        description: str,
        prompt: str,
        agent_type: str = "explorer",
    ) -> str:
        if not self.enable_subagents:
            return "Subagents are disabled in this context."
        parent_session_key = getattr(self._session_local, "session_key", None)
        if not parent_session_key:
            return "Subagent failed: missing parent session context."
        request = SubAgentRequest(
            agent_type=agent_type or "explorer",
            description=description,
            prompt=prompt,
        )
        system_prompt = build_subagent_system_prompt(self.config, request.agent_type)
        child = PoohAgent(
            self.config,
            agent_id=f"subagents-{request.agent_type}",
            readonly=request.agent_type == "explorer",
            enable_subagents=False,
            extra_system_prompt=system_prompt,
        )
        parent_transcript = self.sessions.load_messages(parent_session_key)
        child_session_key = build_subagent_session_key(parent_session_key, request)
        child_prompt = build_subagent_prompt(parent_transcript, request)
        reply = child.ask(child_session_key, child_prompt)
        return (
            f"Subagent({request.agent_type}) finished.\n"
            f"description: {description}\n"
            f"session_id: {reply.session_id}\n\n"
            f"{reply.text}"
        )

    def run_subagent(
        self,
        session_key: str,
        *,
        description: str,
        prompt: str,
        agent_type: str = "explorer",
    ) -> str:
        previous = getattr(self._session_local, "session_key", None)
        self._session_local.session_key = session_key
        try:
            return self._spawn_agent(description=description, prompt=prompt, agent_type=agent_type)
        finally:
            self._session_local.session_key = previous

    def _maybe_generate_title(self, session_key: str, user_text: str, reply_text: str) -> None:
        """If this is the first Q&A in the session (no label yet), generate a short title."""
        existing = self.sessions.get_label(session_key)
        if existing:
            return
        try:
            prompt = (
                "请用中文为以下对话起一个简短标题（10字以内），只输出标题文本，不要加引号和标点：\n"
                f"用户：{user_text[:200]}\n"
                f"助手：{reply_text[:300]}"
            )
            resp = self.client.messages.create(
                model=self.config.model,
                system="你是一个标题生成器，只输出标题文本。",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=30,
            )
            title = ""
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    title += getattr(block, "text", "")
            title = title.strip().strip('"').strip("'").strip("《").strip("》")
            if title:
                self.sessions.set_label(session_key, title)
        except Exception:
            pass

    def ask_stream(
        self,
        session_key: str,
        user_text: str,
        on_event: Any,
    ) -> AgentReply:
        """Streaming variant of `ask`.

        `on_event(kind, payload)` is called with:
          - ("text_delta", {"text": str})
          - ("tool_use_started", {"call_id": str, "name": str})
          - ("tool_use_done", {"id": str, "name": str, "input": dict})
          - ("tool_result", {"tool_use_id": str, "name": str, "content": str, "is_error": bool})
          - ("turn_start", {"turn": int})
          - ("compacted", {"display": str})
          - ("done", {"text": str, "session_id": str, "compacted": bool})
        """

        def _emit(kind: str, payload: dict[str, Any]) -> None:
            try:
                on_event(kind, payload)
            except Exception:
                pass

        self._session_local.session_key = session_key
        self.context.model = self.config.model
        self.context.context_window = self.config.context_window

        self.sessions.append_message(session_key, "user", user_text)

        compacted = self.compact_session(
            session_key,
            user_text_for_prompt=user_text,
            force=False,
        )
        if compacted:
            _emit(
                "compacted",
                {"display": self.get_context_usage(session_key).display},
            )

        final_text = ""
        for turn_idx in range(self.config.max_turns):
            messages = self.sessions.load_messages(session_key)
            system_prompt = self.build_system_prompt(user_text)
            if self.context.should_compact(
                messages, system_prompt, real_total_tokens=self._get_real_total_tokens(session_key)
            ):
                self.compact_session(
                    session_key, user_text_for_prompt=user_text, force=True
                )
                messages = self.sessions.load_messages(session_key)
                _emit(
                    "compacted",
                    {"display": self.get_context_usage(session_key).display},
                )

            _emit("turn_start", {"turn": turn_idx + 1})

            response = self.client.messages.create(
                model=self.config.model,
                system=system_prompt,
                messages=messages,
                tools=self.tools.specs(),
                max_tokens=4096,
                on_event=on_event,
            )
            if response.usage:
                self.sessions.set_last_usage(session_key, response.usage)

            assistant_blocks: list[dict[str, Any]] = []
            tool_result_blocks: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text = getattr(block, "text", "")
                    if text:
                        final_text += text
                        assistant_blocks.append({"type": "text", "text": text})
                elif getattr(block, "type", None) == "tool_use":
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )
                    result = self.tools.execute(block.name, block.input)
                    is_error = result.startswith("Tool ") or result.startswith(
                        "Unknown tool"
                    )
                    _emit(
                        "tool_result",
                        {
                            "tool_use_id": block.id,
                            "name": block.name,
                            "content": result,
                            "is_error": is_error,
                        },
                    )
                    tool_result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                            "is_error": is_error,
                        }
                    )

            if assistant_blocks:
                self.sessions.append_message(session_key, "assistant", assistant_blocks)

            if response.stop_reason != "tool_use":
                break

            if tool_result_blocks:
                self.sessions.append_message(session_key, "user", tool_result_blocks)

        if not final_text.strip():
            final_text = "(empty response)"
        session_id = self.sessions.get_session_id(session_key)

        # Generate title before emitting done, so client receives it in the stream.
        self._maybe_generate_title(session_key, user_text, final_text)
        label = self.sessions.get_label(session_key)

        done_payload: dict[str, Any] = {
            "text": final_text.strip(),
            "session_id": session_id,
            "compacted": compacted,
        }
        if label:
            done_payload["title"] = label
        _emit("done", done_payload)

        return AgentReply(
            text=final_text.strip(),
            session_key=session_key,
            session_id=session_id,
            model=self.config.model,
            compacted=compacted,
        )

    def ask(self, session_key: str, user_text: str) -> AgentReply:
        self._session_local.session_key = session_key
        self.context.model = self.config.model
        self.context.context_window = self.config.context_window
        messages = self.sessions.load_messages(session_key)
        session_id = self.sessions.get_session_id(session_key)
        self.sessions.append_message(session_key, "user", user_text)
        messages.append({"role": "user", "content": user_text})

        compacted = self.compact_session(
            session_key,
            user_text_for_prompt=user_text,
            force=False,
        )
        if compacted:
            messages = self.sessions.load_messages(session_key)

        final_text = ""
        for _ in range(self.config.max_turns):
            messages = self.sessions.load_messages(session_key)
            system_prompt = self.build_system_prompt(user_text)
            if self.context.should_compact(
                messages, system_prompt, real_total_tokens=self._get_real_total_tokens(session_key)
            ):
                self.compact_session(session_key, user_text_for_prompt=user_text, force=True)
                messages = self.sessions.load_messages(session_key)

            response = self.client.messages.create(
                model=self.config.model,
                system=system_prompt,
                messages=messages,
                tools=self.tools.specs(),
                max_tokens=4096,
            )
            if response.usage:
                self.sessions.set_last_usage(session_key, response.usage)
            assistant_blocks: list[dict[str, Any]] = []
            tool_result_blocks: list[dict[str, Any]] = []
            for block in response.content:
                if getattr(block, "type", None) == "text":
                    text = getattr(block, "text", "")
                    if text:
                        final_text += text
                        assistant_blocks.append({"type": "text", "text": text})
                elif getattr(block, "type", None) == "tool_use":
                    assistant_blocks.append(
                        {
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )
                    result = self.tools.execute(block.name, block.input)
                    tool_result_blocks.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result,
                            "is_error": result.startswith("Tool ")
                            or result.startswith("Unknown tool"),
                        }
                    )

            if assistant_blocks:
                self.sessions.append_message(session_key, "assistant", assistant_blocks)
                messages.append({"role": "assistant", "content": assistant_blocks})

            if response.stop_reason != "tool_use":
                break

            if tool_result_blocks:
                self.sessions.append_message(session_key, "user", tool_result_blocks)
                messages.append({"role": "user", "content": tool_result_blocks})

        if not final_text.strip():
            final_text = "(empty response)"
        self._maybe_generate_title(session_key, user_text, final_text)
        return AgentReply(
            text=final_text.strip(),
            session_key=session_key,
            session_id=session_id,
            model=self.config.model,
            compacted=compacted,
        )
