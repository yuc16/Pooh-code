"""
OpenAI-compatible LLM client for Qwen3.5 (and similar models).

Implements the same interface as PoohCodexClient so it can be used as a
drop-in replacement in agent.py and context.py.  Authentication is simple
Bearer-token — no OAuth required.

Configuration (can be overridden via environment variables):
    OPENAI_API_BASE      – API base URL  (default: http://10.8.4.27:3000/v1)
    OPENAI_API_KEY       – API key
    QWEN_DEFAULT_MODEL   – model name override
    QWEN_TIMEOUT         – HTTP timeout in seconds (default: 120)
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

# ── defaults ──────────────────────────────────────────────────────────────────
DEFAULT_API_BASE = "http://10.8.4.27:3000/v1"
DEFAULT_API_KEY  = "sk-FsGjyouPGhChj3PeaZGYTsHCRhUbvHnzhafoP3LfX8ULW6wE"
DEFAULT_MODEL    = "Qwen3.5-397B-A17B"
DEFAULT_TIMEOUT  = 120.0

TRANSIENT_STATUS_CODES = {502, 503, 504}


# ── shared data-classes (same interface as openai_codex.py) ──────────────────
@dataclass
class TextBlock:
    text: str
    type: str = field(default="text", init=False)


@dataclass
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]
    type: str = field(default="tool_use", init=False)


@dataclass
class MessageResponse:
    content: list[Any]
    stop_reason: str
    usage: dict[str, Any] | None = None


# ── public client class ───────────────────────────────────────────────────────
class QwenClient:
    """Calls an OpenAI-compatible /v1/chat/completions endpoint (no OAuth needed)."""

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        timeout: float | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self.base_url   = (base_url or os.getenv("OPENAI_API_BASE", DEFAULT_API_BASE)).rstrip("/")
        self.api_key    = api_key or os.getenv("OPENAI_API_KEY", DEFAULT_API_KEY)
        self.timeout    = timeout if timeout is not None else float(os.getenv("QWEN_TIMEOUT", str(DEFAULT_TIMEOUT)))
        self.verify_ssl = verify_ssl
        self.messages   = _ChatAPI(self)


class _ChatAPI:
    def __init__(self, client: "QwenClient") -> None:
        self._client = client

    def create(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        system: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        on_event: Any = None,
        cancel_event: threading.Event | None = None,
        **_: Any,
    ) -> MessageResponse:
        oai_messages = _build_oai_messages(messages, system)
        body: dict[str, Any] = {
            "model": model,
            "messages": oai_messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = _convert_tools(tools)
            body["tool_choice"] = "auto"
        if max_tokens is not None:
            body["max_tokens"] = max_tokens

        text, tool_calls, finish_reason, usage = _request_chat(
            client=self._client,
            body=body,
            on_event=on_event,
            cancel_event=cancel_event,
        )

        blocks: list[Any] = []
        if text:
            blocks.append(TextBlock(text))
        for tc in tool_calls:
            blocks.append(ToolUseBlock(id=tc["id"], name=tc["name"], input=tc["input"]))
        if not blocks:
            blocks.append(TextBlock(""))

        stop_reason = "tool_use" if tool_calls else "end_turn"
        if finish_reason == "length":
            stop_reason = "max_tokens"
        return MessageResponse(content=blocks, stop_reason=stop_reason, usage=usage)


# ── message conversion: Anthropic-style session transcript → OpenAI format ───

def _build_oai_messages(
    messages: list[dict[str, Any]],
    system: str | None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if system:
        result.append({"role": "system", "content": system})

    for msg in messages:
        role    = msg.get("role", "")
        content = msg.get("content")
        if role == "system":
            # Compressed-history summaries stored as system messages
            result.append({"role": "system", "content": _stringify_content(content)})
        elif role == "user":
            result.extend(_convert_user_message(content))
        elif role == "assistant":
            result.append(_convert_assistant_message(content))

    return _sanitize_oai_messages(result)


def _sanitize_oai_messages(msgs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fix message list to be accepted by OpenAI-compatible APIs.

    Two passes:
    1. Remove orphaned tool messages (no preceding assistant with tool_calls).
       This happens when session compression splits between assistant(tool_use)
       and user(tool_result), causing HTTP 400.
    2. Merge consecutive system messages into one.
       Many models / proxies (including Qwen via vLLM) reject multiple system
       messages; this is triggered whenever a compressed-summary system message
       follows the main agent system prompt.
    """
    # Pass 1: drop orphaned tool messages
    deorphaned: list[dict[str, Any]] = []
    for msg in msgs:
        if msg.get("role") == "tool":
            prev = deorphaned[-1] if deorphaned else None
            if not (
                prev
                and prev.get("role") == "assistant"
                and prev.get("tool_calls")
            ):
                continue  # orphaned — skip
        deorphaned.append(msg)

    # Pass 2: merge consecutive system messages
    merged: list[dict[str, Any]] = []
    for msg in deorphaned:
        if msg.get("role") == "system" and merged and merged[-1].get("role") == "system":
            prev_content = merged[-1].get("content") or ""
            new_content  = msg.get("content") or ""
            merged[-1] = {"role": "system", "content": f"{prev_content}\n\n{new_content}"}
        else:
            merged.append(msg)

    return merged


def _convert_user_message(content: Any) -> list[dict[str, Any]]:
    """
    A user turn may mix plain text, image blocks, and tool_result blocks.
    Returns one {"role":"user"} message plus zero-or-more {"role":"tool"} messages.
    """
    if isinstance(content, str):
        return [{"role": "user", "content": content}]
    if not isinstance(content, list):
        return [{"role": "user", "content": str(content)}]

    text_parts:   list[str]            = []
    image_parts:  list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = str(block.get("text", ""))
            if t:
                text_parts.append(t)
        elif btype == "image":
            media_type = block.get("media_type", "image/png")
            data       = block.get("data", "")
            image_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{media_type};base64,{data}"},
            })
        elif btype == "tool_result":
            tool_id = _plain_tool_id(block.get("tool_use_id"))
            rc      = block.get("content", "")
            if isinstance(rc, list):
                rc = _stringify_content(rc)
            elif not isinstance(rc, str):
                rc = json.dumps(rc, ensure_ascii=False, default=str)
            if block.get("is_error"):
                rc = f"[ERROR] {rc}"
            tool_results.append({"role": "tool", "tool_call_id": tool_id, "content": rc})

    result: list[dict[str, Any]] = []
    combined = "\n".join(text_parts)
    if combined or image_parts:
        if image_parts:
            parts: list[dict[str, Any]] = []
            if combined:
                parts.append({"type": "text", "text": combined})
            parts.extend(image_parts)
            result.append({"role": "user", "content": parts})
        else:
            result.append({"role": "user", "content": combined})
    result.extend(tool_results)
    return result or [{"role": "user", "content": ""}]


def _convert_assistant_message(content: Any) -> dict[str, Any]:
    if isinstance(content, str):
        return {"role": "assistant", "content": content}
    if not isinstance(content, list):
        return {"role": "assistant", "content": str(content)}

    text_parts: list[str]            = []
    tool_calls: list[dict[str, Any]] = []

    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = str(block.get("text", ""))
            if t:
                text_parts.append(t)
        elif btype == "tool_use":
            tc_id = _plain_tool_id(block.get("id"))
            tool_calls.append({
                "id": tc_id,
                "type": "function",
                "function": {
                    "name": str(block.get("name") or ""),
                    "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                },
            })

    msg: dict[str, Any] = {"role": "assistant"}
    combined    = "\n".join(text_parts)
    msg["content"] = combined if combined else None
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Anthropic-style tool specs to OpenAI function-calling format."""
    result = []
    for tool in tools:
        name = tool.get("name")
        if not name:
            continue
        result.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool.get("description") or "",
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        })
    return result


def _stringify_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return json.dumps(content, ensure_ascii=False, default=str) if content else ""


def _plain_tool_id(value: Any) -> str:
    """Strip the legacy Codex-style 'call_id|item_id' separator if present."""
    if isinstance(value, str) and value:
        return value.split("|", 1)[0]
    return "call_0"


# ── HTTP + SSE ────────────────────────────────────────────────────────────────

def _request_chat(
    client: QwenClient,
    body: dict[str, Any],
    on_event: Any,
    cancel_event: threading.Event | None,
) -> tuple[str, list[dict[str, Any]], str, dict[str, Any] | None]:
    url = f"{client.base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {client.api_key}",
        "Content-Type":  "application/json",
        "Accept":        "text/event-stream",
    }
    attempts  = 3
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return _request_once(
                url=url, headers=headers, body=body,
                timeout=client.timeout, verify_ssl=client.verify_ssl,
                on_event=on_event, cancel_event=cancel_event,
            )
        except Exception as exc:
            last_exc = exc
            if cancel_event and cancel_event.is_set():
                raise RuntimeError("Request cancelled.") from exc
            if not _is_transient(exc) or attempt >= attempts:
                raise
            time.sleep(attempt * 2)
    if last_exc:
        raise last_exc
    raise RuntimeError("Chat request failed without a captured exception.")


def _request_once(
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout: float,
    verify_ssl: bool,
    on_event: Any,
    cancel_event: threading.Event | None,
) -> tuple[str, list[dict[str, Any]], str, dict[str, Any] | None]:
    with httpx.Client(timeout=timeout, verify=verify_ssl) as http:
        with http.stream("POST", url, headers=headers, json=body) as resp:
            if resp.status_code != 200:
                raw = resp.read().decode("utf-8", "ignore")
                raise RuntimeError(f"HTTP {resp.status_code}: {raw}")
            return _consume_sse(resp, on_event=on_event, cancel_event=cancel_event)


def _consume_sse(
    response: httpx.Response,
    on_event: Any,
    cancel_event: threading.Event | None,
) -> tuple[str, list[dict[str, Any]], str, dict[str, Any] | None]:
    """Parse an OpenAI-style streaming SSE response.

    Returns (text, tool_calls, finish_reason, usage).
    Also fires on_event callbacks matching the PoohCodexClient event contract.
    """
    text = ""
    tc_buffers: dict[int, dict[str, Any]] = {}  # streaming index → buffer
    finish_reason = "stop"
    usage: dict[str, Any] | None = None
    in_think = False  # tracks whether we are inside a <think>…</think> block

    def emit(kind: str, payload: dict[str, Any]) -> None:
        if on_event is None:
            return
        try:
            on_event(kind, payload)
        except Exception:
            pass

    for chunk in _iter_sse(response, cancel_event):
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("Request cancelled.")

        # Usage arrives in the final chunk when stream_options.include_usage=True
        if chunk.get("usage"):
            u = chunk["usage"]
            usage = {
                "input_tokens":  u.get("prompt_tokens", 0),
                "output_tokens": u.get("completion_tokens", 0),
                "total_tokens":  u.get("total_tokens", 0),
            }

        for choice in chunk.get("choices") or []:
            fr = choice.get("finish_reason")
            if fr:
                finish_reason = fr

            delta = choice.get("delta") or {}

            # ── text content delta ────────────────────────────────────────
            cd = delta.get("content")
            if cd:
                # Detect Qwen3 thinking tokens: <think>…</think>
                if not in_think:
                    if cd.startswith("<think>"):
                        in_think = True
                        rest = cd[len("<think>"):]
                        if "</think>" in rest:
                            reasoning = rest[: rest.index("</think>")]
                            emit("reasoning_delta", {"text": reasoning})
                            after = rest[rest.index("</think>") + len("</think>"):]
                            in_think = False
                            if after:
                                text += after
                                emit("text_delta", {"text": after})
                        else:
                            emit("reasoning_delta", {"text": rest})
                    else:
                        text += cd
                        emit("text_delta", {"text": cd})
                else:
                    if "</think>" in cd:
                        idx = cd.index("</think>")
                        if cd[:idx]:
                            emit("reasoning_delta", {"text": cd[:idx]})
                        emit("reasoning_part_done", {})
                        in_think = False
                        after = cd[idx + len("</think>"):]
                        if after:
                            text += after
                            emit("text_delta", {"text": after})
                    else:
                        emit("reasoning_delta", {"text": cd})

            # ── tool_calls delta ──────────────────────────────────────────
            for tc_delta in delta.get("tool_calls") or []:
                tidx = tc_delta.get("index", 0)
                if tidx not in tc_buffers:
                    tc_buffers[tidx] = {"id": "", "name": "", "arguments": "", "_started": False}
                buf = tc_buffers[tidx]
                if tc_delta.get("id"):
                    buf["id"] = tc_delta["id"]
                fn = tc_delta.get("function") or {}
                if fn.get("name"):
                    buf["name"] = fn["name"]
                buf["arguments"] += fn.get("arguments") or ""
                # Fire tool_use_started once we have both id and name
                if buf["id"] and buf["name"] and not buf["_started"]:
                    buf["_started"] = True
                    emit("tool_use_started", {"call_id": buf["id"], "name": buf["name"]})

    # Finalise tool calls
    tool_calls: list[dict[str, Any]] = []
    for tidx in sorted(tc_buffers):
        buf = tc_buffers[tidx]
        try:
            parsed = json.loads(buf["arguments"] or "{}")
            if not isinstance(parsed, dict):
                # Model returned a JSON scalar instead of an object
                parsed = {"raw": buf["arguments"]}
        except Exception:
            # Arguments were truncated or malformed (often hits max_tokens).
            # Store the partial string so tooling.py can return a clear retry hint.
            parsed = {"raw": buf["arguments"]}
        tool_calls.append({"id": buf["id"], "name": buf["name"], "input": parsed})
        emit("tool_use_done", {
            "call_id": buf["id"],
            "id":      buf["id"],
            "name":    buf["name"],
            "input":   parsed,
        })

    return text, tool_calls, finish_reason, usage


def _iter_sse(response: httpx.Response, cancel_event: threading.Event | None):
    """Yield parsed JSON objects from an OpenAI-style SSE stream."""
    buffer: list[str] = []
    for line in response.iter_lines():
        if cancel_event and cancel_event.is_set():
            response.close()
            return
        if line == "":
            if not buffer:
                continue
            data_parts = [item[5:].strip() for item in buffer if item.startswith("data:")]
            buffer = []
            raw = "\n".join(data_parts).strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                yield json.loads(raw)
            except Exception:
                continue
        else:
            buffer.append(line)


def _is_transient(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError)):
        return True
    msg = str(exc)
    if any(f"HTTP {code}" in msg for code in TRANSIENT_STATUS_CODES):
        return True
    return any(marker in msg.lower() for marker in (
        "connection timeout",
        "temporarily unavailable",
        "upstream connect error",
        "server disconnected without sending a response",
    ))
