from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .openai_codex import PoohCodexClient


CONTEXT_WINDOW_GPT_5_4 = 258_000
COMPACT_MAX_OUTPUT_TOKENS = 20_000
AUTOCOMPACT_BUFFER_TOKENS = 13_000
MANUAL_COMPACT_BUFFER_TOKENS = 3_000


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
        client: PoohCodexClient,
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

    def should_compact(self, messages: list[dict[str, Any]], system_prompt: str) -> bool:
        usage = self.usage(messages, system_prompt)
        return usage.tokens >= usage.auto_compact_threshold

    def compact_messages(
        self,
        messages: list[dict[str, Any]],
        system_prompt: str,
        preserve_recent: int = 8,
    ) -> list[dict[str, Any]]:
        if len(messages) <= preserve_recent + 2:
            return messages

        old_messages = messages[:-preserve_recent]
        recent_messages = messages[-preserve_recent:]

        # Keep the compaction request itself comfortably below the model window.
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
        compact_user = (
            "请总结下面这段较早的对话上下文，供后续继续编码使用。\n"
            "要求：\n"
            "1. 保留用户明确要求和约束。\n"
            "2. 保留关键文件、函数、命令、错误和修复。\n"
            "3. 保留仍未完成的事项。\n"
            "4. 不要编造不存在的信息。\n\n"
            f"原系统提示补充：\n{system_prompt}\n\n"
            f"待压缩对话：\n{transcript}"
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
            "content": "以下是已压缩的历史上下文摘要，请在后续工作中继续遵循：\n\n" + summary,
        }
        if recent_messages and recent_messages[0].get("role") == "system":
            recent_messages = recent_messages[1:]
        return [summary_message, *recent_messages]
