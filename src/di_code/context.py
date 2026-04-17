from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .qwen_client import QwenClient


import os as _os

# gpt-5.4 标准上下文窗口为 272k，Codex 实验性最高可开到 1M。
# 这里取 400k 作为默认值：既高于标准 272k 不会误报，又远低于 1M 仍能正常触发压缩。
# 可通过环境变量 POOH_CONTEXT_WINDOW 覆盖。
CONTEXT_WINDOW_GPT_5_4 = int(_os.getenv("POOH_CONTEXT_WINDOW", "400000"))
COMPACT_MAX_OUTPUT_TOKENS = 20_000
AUTOCOMPACT_BUFFER_TOKENS = 20_000
MANUAL_COMPACT_BUFFER_TOKENS = 5_000

# 压缩后保留的「最近消息」预算：占整个窗口的比例，
# 从 messages 末尾开始累加，直到超过这个预算才停。
# 参考 Claude Code：保留近期对话足够多到不丢失思路即可。
RECENT_BUDGET_RATIO = 0.30
RECENT_MIN_MESSAGES = 4
RECENT_MAX_MESSAGES = 30
# 历史摘要前缀，用于识别"已存在的旧摘要"以便递归压缩
SUMMARY_PREFIX = "以下是已压缩的历史上下文摘要"


def _is_tool_result_only(msg: dict[str, Any]) -> bool:
    """Return True if msg is a user message containing only tool_result blocks."""
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if not isinstance(content, list) or not content:
        return False
    return all(
        isinstance(b, dict) and b.get("type") == "tool_result"
        for b in content
    )


def _is_assistant_with_tool_calls(msg: dict[str, Any]) -> bool:
    """Return True if msg is an assistant message that contains tool_use blocks."""
    if msg.get("role") != "assistant":
        return False
    content = msg.get("content")
    if not isinstance(content, list):
        return False
    return any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)


def estimate_tokens_for_text(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)


def estimate_tokens_for_content(content: Any) -> int:
    if isinstance(content, str):
        return estimate_tokens_for_text(content)
    if isinstance(content, list):
        total = 0
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    total += estimate_tokens_for_text(str(block.get("text", "")))
                elif block_type == "tool_use":
                    total += estimate_tokens_for_text(
                        json.dumps(block.get("input", {}), ensure_ascii=False)
                    ) + 32
                elif block_type == "tool_result":
                    total += estimate_tokens_for_text(
                        json.dumps(block.get("content", ""), ensure_ascii=False, default=str)
                    ) + 32
                else:
                    total += estimate_tokens_for_text(
                        json.dumps(block, ensure_ascii=False, default=str)
                    )
            else:
                total += estimate_tokens_for_text(str(block))
        return total
    if isinstance(content, dict):
        return estimate_tokens_for_text(json.dumps(content, ensure_ascii=False, default=str))
    return estimate_tokens_for_text(str(content))


def estimate_tokens_for_messages(messages: list[dict[str, Any]], system_prompt: str = "") -> int:
    total = estimate_tokens_for_text(system_prompt)
    for message in messages:
        total += 12
        total += estimate_tokens_for_text(message.get("role", ""))
        total += estimate_tokens_for_content(message.get("content", ""))
    return total


def get_context_window(model: str) -> int:
    _ = model
    return CONTEXT_WINDOW_GPT_5_4


def get_effective_context_window(model: str) -> int:
    return get_context_window(model) - COMPACT_MAX_OUTPUT_TOKENS


def get_auto_compact_threshold(model: str) -> int:
    return get_effective_context_window(model) - AUTOCOMPACT_BUFFER_TOKENS


def get_blocking_limit(model: str) -> int:
    return get_effective_context_window(model) - MANUAL_COMPACT_BUFFER_TOKENS


def format_token_count(tokens: int) -> str:
    if tokens >= 1000:
        value = tokens / 1000
        if value >= 100:
            return f"{value:.0f}k"
        return f"{value:.1f}k"
    return str(tokens)


def render_transcript(messages: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for message in messages:
        role = message.get("role", "unknown").upper()
        content = message.get("content", "")
        if isinstance(content, str):
            lines.append(f"{role}:\n{content}")
            continue
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, dict) and block.get("type") == "tool_use":
                    parts.append(
                        "[tool_use] "
                        + str(block.get("name", ""))
                        + " "
                        + json.dumps(block.get("input", {}), ensure_ascii=False)
                    )
                elif isinstance(block, dict) and block.get("type") == "tool_result":
                    parts.append(
                        "[tool_result] "
                        + json.dumps(block.get("content", ""), ensure_ascii=False, default=str)
                    )
                else:
                    parts.append(json.dumps(block, ensure_ascii=False, default=str))
            lines.append(f"{role}:\n" + "\n".join(part for part in parts if part))
            continue
        lines.append(f"{role}:\n{json.dumps(content, ensure_ascii=False, default=str)}")
    return "\n\n".join(lines)


@dataclass
class ContextUsage:
    tokens: int | None
    limit: int
    auto_compact_threshold: int
    blocking_limit: int

    @property
    def display(self) -> str:
        if self.tokens is None:
            return f"--/{format_token_count(self.limit)}"
        return f"{format_token_count(self.tokens)}/{format_token_count(self.limit)}"


class ContextManager:
    def __init__(
        self,
        client: QwenClient,
        model: str,
        *,
        context_window: int | None = None,
    ) -> None:
        self.client = client
        self.model = model
        self.context_window = context_window

    def usage(self, messages: list[dict[str, Any]], system_prompt: str) -> ContextUsage:
        limit = self.context_window or get_context_window(self.model)
        return ContextUsage(
            tokens=estimate_tokens_for_messages(messages, system_prompt),
            limit=limit,
            auto_compact_threshold=(limit - COMPACT_MAX_OUTPUT_TOKENS) - AUTOCOMPACT_BUFFER_TOKENS,
            blocking_limit=(limit - COMPACT_MAX_OUTPUT_TOKENS) - MANUAL_COMPACT_BUFFER_TOKENS,
        )

    def usage_from_real_tokens(self, tokens: int | None) -> ContextUsage:
        limit = self.context_window or get_context_window(self.model)
        return ContextUsage(
            tokens=tokens,
            limit=limit,
            auto_compact_threshold=(limit - COMPACT_MAX_OUTPUT_TOKENS) - AUTOCOMPACT_BUFFER_TOKENS,
            blocking_limit=(limit - COMPACT_MAX_OUTPUT_TOKENS) - MANUAL_COMPACT_BUFFER_TOKENS,
        )

    def should_compact(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        real_total_tokens: int | None = None,
    ) -> bool:
        # 优先使用 API 返回的真实 usage，更准确
        if real_total_tokens is not None and real_total_tokens > 0:
            usage = self.usage_from_real_tokens(real_total_tokens)
        else:
            usage = self.usage(messages, system_prompt)
        if usage.tokens is None:
            return False
        return usage.tokens >= usage.auto_compact_threshold

    def _split_recent_by_budget(
        self,
        messages: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """按 token 预算从尾部切出 recent 段，返回 (old, recent)。

        预算 = 窗口 * RECENT_BUDGET_RATIO，硬上下界由 RECENT_MIN/MAX_MESSAGES 限制。
        """
        limit = self.context_window or get_context_window(self.model)
        budget = int(limit * RECENT_BUDGET_RATIO)
        recent: list[dict[str, Any]] = []
        running = 0
        # 从末尾向前累加
        for msg in reversed(messages):
            cost = 12 + estimate_tokens_for_text(msg.get("role", "")) + estimate_tokens_for_content(
                msg.get("content", "")
            )
            if recent and running + cost > budget and len(recent) >= RECENT_MIN_MESSAGES:
                break
            recent.insert(0, msg)
            running += cost
            if len(recent) >= RECENT_MAX_MESSAGES:
                break
        # 至少保留 RECENT_MIN_MESSAGES 条
        if len(recent) < RECENT_MIN_MESSAGES and len(messages) >= RECENT_MIN_MESSAGES:
            recent = messages[-RECENT_MIN_MESSAGES:]
        old = messages[: len(messages) - len(recent)]
        return old, recent

    def compact_messages(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        preserve_recent: int | None = None,
    ) -> list[dict[str, Any]]:
        if len(messages) < RECENT_MIN_MESSAGES + 2:
            return messages

        # ── 1. 自适应切分 recent ──
        if preserve_recent is not None:
            # 兼容老接口
            old_messages = messages[:-preserve_recent]
            recent_messages = messages[-preserve_recent:]
        else:
            old_messages, recent_messages = self._split_recent_by_budget(messages)

        if not old_messages:
            return messages

        # ── 1b. 边界修正：避免 recent 以孤立的 tool_result 开头 ───────────────
        # 如果 recent[0] 是纯 tool_result 用户消息（对应的 assistant tool_use
        # 被划入了 old），必须把 old 末尾那条 assistant 消息移进 recent，
        # 否则发给 API 时会因"孤立 tool 消息"报 400。
        if (
            recent_messages
            and old_messages
            and _is_tool_result_only(recent_messages[0])
            and _is_assistant_with_tool_calls(old_messages[-1])
        ):
            recent_messages = [old_messages.pop()] + recent_messages
            if not old_messages:
                return messages

        # ── 2. 递归压缩：如果第一条已是旧摘要，把它也当成"待压缩"输入，
        # 输出的新摘要会"覆盖"它，避免摘要无限累积。
        prior_summary: str | None = None
        if (
            old_messages
            and old_messages[0].get("role") == "system"
            and isinstance(old_messages[0].get("content"), str)
            and old_messages[0]["content"].startswith(SUMMARY_PREFIX)
        ):
            prior_summary = old_messages[0]["content"]
            old_messages = old_messages[1:]
            if not old_messages:
                # 只有旧摘要没新增 old → 不需要再压缩
                return messages

        # 压缩请求自身的安全上限
        while old_messages and estimate_tokens_for_messages(old_messages) > 160_000:
            drop = max(1, len(old_messages) // 10)
            old_messages = old_messages[drop:]

        transcript = render_transcript(old_messages)
        compact_system = (
            "CRITICAL: Respond with text only. Do not call any tools.\n\n"
            "You are compacting an ongoing coding session. Produce a precise Chinese summary "
            "that preserves user intent, important code paths, files, commands, tool results, "
            "open questions, and the next actionable step.\n"
            "Return only the summary body."
        )
        prior_block = (
            f"\n已有的历史摘要（请合并进新摘要，不要丢失其中信息）：\n{prior_summary}\n"
            if prior_summary
            else ""
        )
        compact_user = (
            "请总结下面这段较早的对话上下文，供后续继续编码使用。\n"
            "要求：\n"
            "1. 保留用户明确要求和约束。\n"
            "2. 保留关键文件、函数、命令、错误和修复。\n"
            "3. 保留仍未完成的事项。\n"
            "4. 不要编造不存在的信息。\n"
            "5. 如果提供了已有的历史摘要，请将其要点合并进新摘要，"
            "保证整体长度受控、不丢失关键信息。\n\n"
            f"原系统提示补充：\n{system_prompt}\n"
            f"{prior_block}\n"
            f"新增待压缩对话：\n{transcript}"
        )
        response = self.client.messages.create(
            model=self.model,
            system=compact_system,
            messages=[{"role": "user", "content": compact_user}],
        )
        summary_parts = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                summary_parts.append(getattr(block, "text", ""))
        summary = "\n".join(part for part in summary_parts if part).strip()
        if not summary:
            return messages

        summary_message = {
            "role": "system",
            "content": f"{SUMMARY_PREFIX}，请在后续工作中继续遵循：\n\n" + summary,
        }
        # 只剥离 recent 段开头的"旧摘要"，普通 system 消息保留
        if (
            recent_messages
            and recent_messages[0].get("role") == "system"
            and isinstance(recent_messages[0].get("content"), str)
            and recent_messages[0]["content"].startswith(SUMMARY_PREFIX)
        ):
            recent_messages = recent_messages[1:]
        return [summary_message, *recent_messages]
