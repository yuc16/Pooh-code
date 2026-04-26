from __future__ import annotations

import json
import os
import threading
from typing import Any

from .config import AgentConfig
from .context import ContextManager, ContextUsage
from .models import AgentReply, ToolSpec, ToolSpec
from .openai_codex import PoohCodexClient
from .file_processing import process_file
from .output_files import OUTPUT_DIR, ensure_session_output_dir
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


def _is_cancelled_error(exc: Exception) -> bool:
    return "cancelled" in str(exc).lower()


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
        self._register_skill_tool()

    def _current_session_context(self) -> tuple[str | None, str | None]:
        session_key = getattr(self._session_local, "session_key", None)
        if not session_key:
            return None, None
        session_id = getattr(self._session_local, "session_id", None) or self.sessions.get_session_id(session_key)
        output_dir = str(ensure_session_output_dir(session_id))
        return session_key, output_dir

    def _register_skill_tool(self) -> None:
        self.skills.discover()
        available = self.skills.list_names()
        names_hint = ", ".join(available)
        name_schema: dict[str, Any] = {
            "type": "string",
            "description": "skill 名字,例如 github-push",
        }
        if available:
            name_schema["enum"] = available
        self.tools.register_tool(
            ToolSpec(
                name="use_skill",
                description=(
                    "加载某个 skill 的完整指令。当用户意图匹配 system prompt 中 "
                    "## Skills 列表里某条 description 时,先调用此工具拿到完整步骤再执行。"
                    f"当前可用 skill: {names_hint or '(none)'}。"
                ),
                input_schema={
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": name_schema,
                    },
                },
            ),
            lambda name: self.skills.get_body(name),
            replace=True,
        )

    def _refresh_skills(self) -> None:
        self._register_skill_tool()

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
        self._refresh_skills()
        parts = [self._load_bootstrap_files(), self.skills.render_metadata_for_prompt()]
        session_key, session_output_dir = self._current_session_context()
        session_id = getattr(self._session_local, "session_id", None)
        if session_key and not session_id:
            session_id = self.sessions.get_session_id(session_key)
        runtime = {
            "agent_name": self.config.name,
            "agent_id": self.agent_id,
            "readonly": self.readonly,
            "subagents_enabled": self.enable_subagents,
            "model": self.config.model,
            "project_root": str(PROJECT_ROOT),
            "runtime_root": str(RUNTIME_DIR),
            "output_root": str(OUTPUT_DIR),
            "cwd": str(RUNTIME_DIR.parent),  # workplace/，bash 工具的默认工作目录
            "timezone": SHANGHAI_TZ_NAME,
            "local_time": shanghai_now_iso(),
        }
        if session_key and session_id and session_output_dir:
            runtime["session_key"] = session_key
            runtime["current_session_id"] = session_id
            runtime["session_output_dir"] = session_output_dir
            runtime["session_output_dir_relative_to_workplace"] = f"output/{session_id}"
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
        self,
        session_key: str,
        pending_user_text: str = "",
        user_text_for_prompt: str = "",
        session_id: str | None = None,
    ) -> ContextUsage:
        self.context.model = self.config.model
        self.context.context_window = self.config.context_window
        if not pending_user_text:
            usage = self.sessions.get_last_usage(session_key, session_id=session_id)
            real_total_tokens: int | None = None
            if isinstance(usage, dict):
                raw = usage.get("total_tokens")
                if isinstance(raw, int) and raw > 0:
                    real_total_tokens = raw
            if real_total_tokens is not None:
                return self.context.usage_from_real_tokens(real_total_tokens)
            # 没有真实 usage（新会话 / 刚 compact / 刚 clear）时回退到 message
            # 估算，避免前端显示成 `0/258k` 或 `--/258k`。估算偏保守，但比 0 真。
            messages = self.sessions.load_messages(session_key, session_id=session_id)
            if not messages:
                return self.context.usage_from_real_tokens(None)
            return self.context.usage(messages, self.build_system_prompt(user_text_for_prompt))
        messages = self.sessions.load_messages(session_key, session_id=session_id)
        if pending_user_text:
            messages = [*messages, {"role": "user", "content": pending_user_text}]
        return self.context.usage(messages, self.build_system_prompt(user_text_for_prompt))

    def _get_real_total_tokens(self, session_key: str, session_id: str | None = None) -> int | None:
        usage = self.sessions.get_last_usage(session_key, session_id=session_id)
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
        session_id: str | None = None,
        on_event: Any | None = None,
    ) -> bool:
        """同步压缩。`on_event(kind, payload)` 可选；如果传入，则在真正进入
        摘要 LLM 调用之前发 `compacting`，结束后无论是否产生新摘要都不会
        再额外发，由调用方根据返回值决定是否发 `compacted`。这样前端在
        长上下文压缩期间就有「上下文压缩中…」可以显示，而不是死寂。"""
        self.context.model = self.config.model
        self.context.context_window = self.config.context_window
        messages = self.sessions.load_messages(session_key, session_id=session_id)
        if not messages:
            return False
        system_prompt = self.build_system_prompt(user_text_for_prompt)
        real_tokens = self._get_real_total_tokens(session_key, session_id=session_id)
        if not force and not self.context.should_compact(
            messages, system_prompt, real_total_tokens=real_tokens
        ):
            return False
        if on_event is not None:
            try:
                usage = self.context.usage_from_real_tokens(real_tokens) if real_tokens else self.context.usage(messages, system_prompt)
                on_event(
                    "compacting",
                    {
                        "reason": "force" if force else "auto",
                        "display": usage.display,
                    },
                )
            except Exception:
                pass
        compacted = self.context.compact_messages(messages, system_prompt)
        if compacted == messages:
            return False
        self.sessions.replace_messages(session_key, compacted, session_id=session_id)
        self.sessions.invalidate_last_usage(session_key, session_id=session_id)
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

    def _maybe_generate_title(
        self,
        session_key: str,
        user_text: str,
        reply_text: str,
        session_id: str | None = None,
    ) -> None:
        """If this is the first Q&A in the session (no label yet), generate a short title."""
        existing = self.sessions.get_label(session_key, session_id=session_id)
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
                self.sessions.set_label(session_key, title, session_id=session_id)
        except Exception:
            pass

    def ask_stream(
        self,
        session_key: str,
        user_text: str,
        on_event: Any,
        *,
        session_id: str | None = None,
        cancel_event: threading.Event | None = None,
        files: list[str] | None = None,
        inject_drain: Any | None = None,
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

        actual_session_id = session_id or self.sessions.get_session_id(session_key)
        previous_session_key = getattr(self._session_local, "session_key", None)
        previous_session_id = getattr(self._session_local, "session_id", None)
        self._session_local.session_key = session_key
        self._session_local.session_id = actual_session_id
        try:
            self._refresh_skills()
            self.context.model = self.config.model
            self.context.context_window = self.config.context_window
            ensure_session_output_dir(actual_session_id)

            # 构建用户消息内容：纯文本或多模态（文本+图片+文档摘要）
            user_content: Any = user_text
            if files:
                from pathlib import Path
                content_blocks: list[dict[str, Any]] = []
                if user_text:
                    content_blocks.append({"type": "text", "text": user_text})
                for fpath in files:
                    try:
                        blocks = process_file(Path(fpath))
                        content_blocks.extend(blocks)
                    except Exception as exc:
                        content_blocks.append({"type": "text", "text": f"[文件处理失败: {Path(fpath).name} - {exc}]"})
                user_content = content_blocks if content_blocks else user_text

            self.sessions.append_message(
                session_key,
                "user",
                user_content,
                session_id=actual_session_id,
                mode="text",
                model=self.config.model,
            )

            compacted = self.compact_session(
                session_key,
                user_text_for_prompt=user_text,
                force=False,
                session_id=actual_session_id,
                on_event=_emit,
            )
            if compacted:
                _emit(
                    "compacted",
                    {"display": self.get_context_usage(session_key, session_id=actual_session_id).display},
                )

            final_text = ""
            for turn_idx in range(self.config.max_turns):
                if cancel_event and cancel_event.is_set():
                    final_text += "\n\n[任务已取消]"
                    _emit("cancelled", {"session_id": actual_session_id})
                    break
                messages = self.sessions.load_messages(session_key, session_id=actual_session_id)
                system_prompt = self.build_system_prompt(user_text)
                if self.context.should_compact(
                    messages,
                    system_prompt,
                    real_total_tokens=self._get_real_total_tokens(session_key, session_id=actual_session_id),
                ):
                    self.compact_session(
                        session_key,
                        user_text_for_prompt=user_text,
                        force=True,
                        session_id=actual_session_id,
                        on_event=_emit,
                    )
                    messages = self.sessions.load_messages(session_key, session_id=actual_session_id)
                    _emit(
                        "compacted",
                        {"display": self.get_context_usage(session_key, session_id=actual_session_id).display},
                    )
                _emit("turn_start", {"turn": turn_idx + 1})

                try:
                    response = self.client.messages.create(
                        model=self.config.model,
                        system=system_prompt,
                        messages=messages,
                        tools=self.tools.specs(),
                        max_tokens=4096,
                        on_event=on_event,
                        cancel_event=cancel_event,
                    )
                except RuntimeError as exc:
                    if _is_cancelled_error(exc):
                        final_text += "\n\n[任务已取消]"
                        _emit("cancelled", {"session_id": actual_session_id})
                        break
                    raise
                if response.usage:
                    self.sessions.set_last_usage(session_key, response.usage, session_id=actual_session_id)

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
                    self.sessions.append_message(
                        session_key,
                        "assistant",
                        assistant_blocks,
                        session_id=actual_session_id,
                        mode="text",
                        model=self.config.model,
                    )

                if response.stop_reason != "tool_use":
                    break

                if tool_result_blocks:
                    self.sessions.append_message(
                        session_key,
                        "user",
                        tool_result_blocks,
                        session_id=actual_session_id,
                        mode="text",
                        model=self.config.model,
                    )

                # ── 检查用户插话 ──
                if inject_drain:
                    injected_msgs = inject_drain()
                    for inj_text in injected_msgs:
                        _emit("injected", {"text": inj_text})
                        self.sessions.append_message(
                            session_key,
                            "user",
                            inj_text,
                            session_id=actual_session_id,
                            mode="text",
                            model=self.config.model,
                        )
            else:
                # for 循环正常跑完意味着跑满 max_turns 还在 tool_use,被强制截断
                note = (
                    f"\n\n[已达到 max_turns={self.config.max_turns} 上限,任务被截断。"
                    f"再发一条消息可让我继续。]"
                )
                final_text += note
                _emit("truncated", {"max_turns": self.config.max_turns})

            if not final_text.strip():
                final_text = "(empty response)"
            session_id = actual_session_id

            # Generate title before emitting done, so client receives it in the stream.
            self._maybe_generate_title(session_key, user_text, final_text, session_id=actual_session_id)
            label = self.sessions.get_label(session_key, session_id=actual_session_id)

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
        finally:
            self._session_local.session_key = previous_session_key
            self._session_local.session_id = previous_session_id

    def ask(self, session_key: str, user_text: str) -> AgentReply:
        actual_session_id = self.sessions.get_session_id(session_key)
        return self.ask_for_session(session_key, user_text, session_id=actual_session_id)

    def ask_for_session(
        self,
        session_key: str,
        user_text: str,
        *,
        session_id: str,
    ) -> AgentReply:
        previous_session_key = getattr(self._session_local, "session_key", None)
        previous_session_id = getattr(self._session_local, "session_id", None)
        self._session_local.session_key = session_key
        self._session_local.session_id = session_id
        try:
            self._refresh_skills()
            self.context.model = self.config.model
            self.context.context_window = self.config.context_window
            messages = self.sessions.load_messages(session_key, session_id=session_id)
            ensure_session_output_dir(session_id)
            self.sessions.append_message(
                session_key,
                "user",
                user_text,
                session_id=session_id,
                mode="text",
                model=self.config.model,
            )
            messages.append({"role": "user", "content": user_text})

            compacted = self.compact_session(
                session_key,
                user_text_for_prompt=user_text,
                force=False,
                session_id=session_id,
            )
            if compacted:
                messages = self.sessions.load_messages(session_key, session_id=session_id)

            final_text = ""
            for _ in range(self.config.max_turns):
                messages = self.sessions.load_messages(session_key, session_id=session_id)
                system_prompt = self.build_system_prompt(user_text)
                if self.context.should_compact(
                    messages,
                    system_prompt,
                    real_total_tokens=self._get_real_total_tokens(session_key, session_id=session_id),
                ):
                    self.compact_session(
                        session_key,
                        user_text_for_prompt=user_text,
                        force=True,
                        session_id=session_id,
                    )
                    messages = self.sessions.load_messages(session_key, session_id=session_id)

                response = self.client.messages.create(
                    model=self.config.model,
                    system=system_prompt,
                    messages=messages,
                    tools=self.tools.specs(),
                    max_tokens=4096,
                )
                if response.usage:
                    self.sessions.set_last_usage(session_key, response.usage, session_id=session_id)
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
                    self.sessions.append_message(
                        session_key,
                        "assistant",
                        assistant_blocks,
                        session_id=session_id,
                        mode="text",
                        model=self.config.model,
                    )
                    messages.append({"role": "assistant", "content": assistant_blocks})

                if response.stop_reason != "tool_use":
                    break

                if tool_result_blocks:
                    self.sessions.append_message(
                        session_key,
                        "user",
                        tool_result_blocks,
                        session_id=session_id,
                        mode="text",
                        model=self.config.model,
                    )
                    messages.append({"role": "user", "content": tool_result_blocks})
            else:
                final_text += (
                    f"\n\n[已达到 max_turns={self.config.max_turns} 上限,任务被截断。"
                    f"再发一条消息可让我继续。]"
                )

            if not final_text.strip():
                final_text = "(empty response)"
            self._maybe_generate_title(session_key, user_text, final_text, session_id=session_id)
            return AgentReply(
                text=final_text.strip(),
                session_key=session_key,
                session_id=session_id,
                model=self.config.model,
                compacted=compacted,
            )
        finally:
            self._session_local.session_key = previous_session_key
            self._session_local.session_id = previous_session_id
