from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

try:
    from oauth_cli_kit import get_token, login_oauth_interactive
except ImportError:
    get_token = None
    login_oauth_interactive = None


DEFAULT_CODEX_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_ORIGINATOR = "pooh-code"
DEFAULT_MODEL = "gpt-5.4"
TRANSIENT_STATUS_CODES = {502, 503, 504}
FINISH_REASON_MAP = {
    "completed": "end_turn",
    "incomplete": "max_tokens",
    "failed": "error",
    "cancelled": "error",
}


os.environ.setdefault("ANTHROPIC_API_KEY", "chatgpt-plus-oauth")


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


class _MessagesAPI:
    def __init__(self, client: "PoohCodexClient"):
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
        instructions, input_items = _convert_messages(messages, system)
        body: dict[str, Any] = {
            "model": _resolve_model_name(model),
            "store": False,
            "stream": True,
            "instructions": instructions,
            "input": input_items,
            "text": {"verbosity": os.getenv("OPENAI_CODEX_VERBOSITY", "medium")},
            "reasoning": {
                "effort": os.getenv("OPENAI_CODEX_REASONING_EFFORT", "medium"),
                "summary": os.getenv("OPENAI_CODEX_REASONING_SUMMARY", "auto"),
            },
            "include": ["reasoning.encrypted_content"],
            "prompt_cache_key": _prompt_cache_key(system, messages),
            "tool_choice": "auto",
            "parallel_tool_calls": True,
        }
        if tools:
            body["tools"] = _convert_tools(tools)

        token = ensure_openai_codex_auth()
        headers = _build_headers(
            account_id=getattr(token, "account_id", ""),
            access_token=getattr(token, "access", ""),
            originator=self._client.originator,
        )
        try:
            content, tool_calls, finish_reason, usage = _request_codex(
                url=self._client.base_url,
                headers=headers,
                body=body,
                timeout_seconds=self._client.timeout_seconds,
                verify_ssl=self._client.verify_ssl,
                on_event=on_event,
                cancel_event=cancel_event,
            )
        except RuntimeError as exc:
            should_retry = (
                "invalid or expired" in str(exc)
                and sys.stdin.isatty()
                and sys.stdout.isatty()
            )
            if not should_retry:
                raise
            token = _ensure_openai_codex_auth(interactive=True, force_login=True)
            headers = _build_headers(
                account_id=getattr(token, "account_id", ""),
                access_token=getattr(token, "access", ""),
                originator=self._client.originator,
            )
            content, tool_calls, finish_reason, usage = _request_codex(
                url=self._client.base_url,
                headers=headers,
                body=body,
                timeout_seconds=self._client.timeout_seconds,
                verify_ssl=self._client.verify_ssl,
                on_event=on_event,
                cancel_event=cancel_event,
            )

        blocks: list[Any] = []
        if content:
            blocks.append(TextBlock(content))
        for tool_call in tool_calls:
            blocks.append(
                ToolUseBlock(
                    id=tool_call["id"],
                    name=tool_call["name"],
                    input=tool_call["input"],
                )
            )
        if not blocks:
            blocks.append(TextBlock(""))
        stop_reason = "tool_use" if tool_calls else FINISH_REASON_MAP.get(
            finish_reason, "end_turn"
        )
        return MessageResponse(content=blocks, stop_reason=stop_reason, usage=usage)


class PoohCodexClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = _resolve_codex_url(base_url)
        self.originator = os.getenv("OPENAI_CODEX_ORIGINATOR", DEFAULT_ORIGINATOR)
        self.verify_ssl = _env_bool("OPENAI_CODEX_VERIFY_SSL", True)
        self.timeout_seconds = float(os.getenv("OPENAI_CODEX_TIMEOUT", "60"))
        self.messages = _MessagesAPI(self)


def ensure_openai_codex_auth(interactive: bool | None = None):
    return _ensure_openai_codex_auth(interactive=interactive, force_login=False)


def refresh_openai_codex_auth(interactive: bool | None = True):
    return _ensure_openai_codex_auth(interactive=interactive, force_login=True)


def _ensure_openai_codex_auth(*, interactive: bool | None, force_login: bool):
    if get_token is None:
        raise RuntimeError(
            "oauth-cli-kit is not installed. Run `uv sync` before using OpenAI Codex."
        )

    token = None
    if not force_login:
        try:
            token = get_token()
        except Exception:
            token = None

    if token and getattr(token, "access", None):
        return token

    if interactive is None:
        interactive = (
            _env_bool("OPENAI_CODEX_AUTO_LOGIN", True)
            and sys.stdin.isatty()
            and sys.stdout.isatty()
        )

    if not interactive:
        raise RuntimeError(
            "OpenAI Codex OAuth login required. Run `uv run pooh-code-login`."
        )
    if login_oauth_interactive is None:
        raise RuntimeError(
            "oauth-cli-kit is installed without interactive login support."
        )

    token = login_oauth_interactive(print_fn=print, prompt_fn=input)
    if token and getattr(token, "access", None):
        return token
    raise RuntimeError("OpenAI Codex OAuth login failed.")


def _resolve_codex_url(base_url: str | None) -> str:
    explicit = os.getenv("OPENAI_CODEX_BASE_URL")
    if explicit:
        value = explicit.rstrip("/")
    elif base_url:
        value = base_url.rstrip("/")
    else:
        value = DEFAULT_CODEX_URL

    if value.endswith("/backend-api"):
        return value + "/codex/responses"
    if "chatgpt.com/backend-api/codex/responses" in value:
        return value
    if "chatgpt.com/backend-api" in value:
        return value.rstrip("/") + "/codex/responses"
    if explicit:
        return value
    return DEFAULT_CODEX_URL


def _build_headers(account_id: str, access_token: str, originator: str) -> dict[str, str]:
    if not access_token:
        raise RuntimeError("OpenAI Codex OAuth token is empty.")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "OpenAI-Beta": "responses=experimental",
        "originator": originator,
        "User-Agent": "pooh-code (python)",
        "accept": "text/event-stream",
        "content-type": "application/json",
    }
    if account_id:
        headers["chatgpt-account-id"] = account_id
    return headers


def _request_codex(
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_seconds: float,
    verify_ssl: bool,
    on_event: Any = None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, list[dict[str, Any]], str, dict[str, Any] | None]:
    attempts = 3
    last_exc: Exception | None = None
    current_verify_ssl = verify_ssl
    for attempt in range(1, attempts + 1):
        try:
            return _request_codex_once(
                url=url,
                headers=headers,
                body=body,
                timeout_seconds=timeout_seconds,
                verify_ssl=current_verify_ssl,
                on_event=on_event,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            last_exc = exc
            message = str(exc)
            if "CERTIFICATE_VERIFY_FAILED" in message and current_verify_ssl:
                current_verify_ssl = False
                continue
            if attempt >= attempts or not _is_transient_codex_error(exc):
                raise
            time.sleep(attempt)
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("OpenAI Codex request failed without a captured exception.")


def _request_codex_once(
    *,
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    timeout_seconds: float,
    verify_ssl: bool,
    on_event: Any = None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, list[dict[str, Any]], str, dict[str, Any] | None]:
    with httpx.Client(timeout=timeout_seconds, verify=verify_ssl) as client:
        with client.stream("POST", url, headers=headers, json=body) as response:
            if response.status_code != 200:
                raw = response.read().decode("utf-8", "ignore")
                raise RuntimeError(_friendly_error(response.status_code, raw))
            return _consume_sse(response, on_event=on_event, cancel_event=cancel_event)


def _consume_sse(
    response: httpx.Response,
    on_event: Any = None,
    cancel_event: threading.Event | None = None,
) -> tuple[str, list[dict[str, Any]], str, dict[str, Any] | None]:
    content = ""
    tool_calls: list[dict[str, Any]] = []
    tool_call_buffers: dict[str, dict[str, Any]] = {}
    finish_reason = "completed"
    usage: dict[str, Any] | None = None

    def _emit(kind: str, payload: dict[str, Any]) -> None:
        if on_event is None:
            return
        try:
            on_event(kind, payload)
        except Exception:
            pass

    for event in _iter_sse(response, cancel_event=cancel_event):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("OpenAI Codex response cancelled.")
        event_type = event.get("type")
        if event_type == "response.output_item.added":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if call_id:
                    tool_call_buffers[call_id] = {
                        "id": item.get("id") or "fc_0",
                        "name": item.get("name") or "",
                        "arguments": item.get("arguments") or "",
                    }
                    _emit(
                        "tool_use_started",
                        {
                            "call_id": call_id,
                            "name": item.get("name") or "",
                        },
                    )
        elif event_type == "response.output_text.delta":
            delta = event.get("delta") or ""
            content += delta
            if delta:
                _emit("text_delta", {"text": delta})
        elif event_type in (
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
        ):
            delta = event.get("delta") or ""
            if delta:
                _emit("reasoning_delta", {"text": delta})
        elif event_type in (
            "response.reasoning_summary_part.added",
            "response.reasoning_summary_text.added",
        ):
            _emit("reasoning_part_added", {})
        elif event_type in (
            "response.reasoning_summary_text.done",
            "response.reasoning_summary_part.done",
        ):
            _emit("reasoning_part_done", {})
        elif event_type == "response.function_call_arguments.delta":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                tool_call_buffers[call_id]["arguments"] += event.get("delta") or ""
        elif event_type == "response.function_call_arguments.done":
            call_id = event.get("call_id")
            if call_id and call_id in tool_call_buffers:
                tool_call_buffers[call_id]["arguments"] = event.get("arguments") or ""
        elif event_type == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                call_id = item.get("call_id")
                if not call_id:
                    continue
                buffer = tool_call_buffers.get(call_id) or {}
                raw_args = buffer.get("arguments") or item.get("arguments") or "{}"
                try:
                    parsed_args = json.loads(raw_args)
                except Exception:
                    parsed_args = {"raw": raw_args}
                full_id = f"{call_id}|{buffer.get('id') or item.get('id') or 'fc_0'}"
                tool_calls.append(
                    {
                        "id": full_id,
                        "name": buffer.get("name") or item.get("name") or "",
                        "input": parsed_args,
                    }
                )
                _emit(
                    "tool_use_done",
                    {
                        "call_id": call_id,
                        "id": full_id,
                        "name": buffer.get("name") or item.get("name") or "",
                        "input": parsed_args,
                    },
                )
        elif event_type == "response.completed":
            response_obj = event.get("response") or {}
            finish_reason = response_obj.get("status") or "completed"
            usage = response_obj.get("usage")
        elif event_type in {"error", "response.failed"}:
            raise RuntimeError("OpenAI Codex response failed.")

    return content, tool_calls, finish_reason, usage


def _iter_sse(response: httpx.Response, cancel_event: threading.Event | None = None):
    buffer: list[str] = []
    for line in response.iter_lines():
        if cancel_event is not None and cancel_event.is_set():
            response.close()
            raise RuntimeError("OpenAI Codex response cancelled.")
        if line == "":
            if not buffer:
                continue
            payload = []
            for item in buffer:
                if item.startswith("data:"):
                    payload.append(item[5:].strip())
            buffer = []
            raw = "\n".join(payload).strip()
            if not raw or raw == "[DONE]":
                continue
            try:
                yield json.loads(raw)
            except Exception:
                continue
            continue
        buffer.append(line)


def _convert_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted = []
    for tool in tools:
        name = tool.get("name")
        if not name:
            continue
        converted.append(
            {
                "type": "function",
                "name": name,
                "description": tool.get("description") or "",
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            }
        )
    return converted


def _convert_messages(
    messages: list[dict[str, Any]], system: str | None
) -> tuple[str, list[dict[str, Any]]]:
    instructions = [system] if system else []
    input_items: list[dict[str, Any]] = []

    for index, message in enumerate(messages):
        role = message.get("role")
        content = message.get("content")

        if role == "system":
            system_text = _stringify_text(content)
            if system_text:
                instructions.append(system_text)
            continue

        if role == "user":
            input_items.extend(_convert_user_content(content))
            continue

        if role == "assistant":
            input_items.extend(_convert_assistant_content(content, index))
            continue

    return "\n\n".join(part for part in instructions if part), input_items


def _convert_user_content(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [_user_text_message(content)]

    if not isinstance(content, list):
        return [_user_text_message("")]

    items: list[dict[str, Any]] = []
    text_parts: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        part_type = part.get("type")
        if part_type == "text":
            text_parts.append({"type": "input_text", "text": str(part.get("text", ""))})
        elif part_type == "image":
            # 多模态图片块 → Codex input_image
            media_type = part.get("media_type", "image/png")
            data = part.get("data", "")
            text_parts.append({
                "type": "input_image",
                "image_url": f"data:{media_type};base64,{data}",
            })
        elif part_type == "tool_result":
            call_id, _ = _split_tool_call_id(part.get("tool_use_id"))
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": _stringify_tool_output(part.get("content")),
                }
            )
    if text_parts:
        items.insert(0, {"role": "user", "content": text_parts})
    return items or [_user_text_message("")]


def _convert_assistant_content(content: Any, index: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    text_parts: list[dict[str, Any]] = []
    if isinstance(content, str):
        return [_assistant_text_message(content, index)] if content else []
    if not isinstance(content, list):
        return []

    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text = str(part.get("text", ""))
            if text:
                text_parts.append({"type": "output_text", "text": text})
        elif part.get("type") == "tool_use":
            tool_id = part.get("id") or f"call_{index}"
            call_id, item_id = _split_tool_call_id(tool_id)
            items.append(
                {
                    "type": "function_call",
                    "id": item_id or f"fc_{index}",
                    "call_id": call_id,
                    "name": part.get("name") or "",
                    "arguments": json.dumps(part.get("input") or {}, ensure_ascii=False),
                }
            )
    if text_parts:
        items.insert(
            0,
            {
                "type": "message",
                "role": "assistant",
                "content": text_parts,
                "status": "completed",
                "id": f"msg_{index}",
            },
        )
    return items


def _user_text_message(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "input_text", "text": text}]}


def _assistant_text_message(text: str, index: int) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "content": [{"type": "output_text", "text": text}],
        "status": "completed",
        "id": f"msg_{index}",
    }


def _stringify_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                parts.append(str(part.get("text", "")))
        return "\n".join(part for part in parts if part)
    return ""


def _stringify_tool_output(content: Any) -> str:
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, default=str)


def _split_tool_call_id(value: Any) -> tuple[str, str | None]:
    if isinstance(value, str) and value:
        if "|" in value:
            call_id, item_id = value.split("|", 1)
            return call_id, item_id or None
        return value, None
    return "call_0", None


def _resolve_model_name(model: str) -> str:
    normalized = _strip_model_prefix(model)
    if normalized and not normalized.startswith("claude-"):
        return normalized
    env_model = _strip_model_prefix(os.getenv("MODEL_ID", "").strip())
    if env_model and not env_model.startswith("claude-"):
        return env_model
    override = _strip_model_prefix(os.getenv("OPENAI_CODEX_MODEL", "").strip())
    if override:
        return override
    return os.getenv("OPENAI_CODEX_DEFAULT_MODEL", DEFAULT_MODEL)


def _strip_model_prefix(model: str) -> str:
    if model.startswith("openai-codex/") or model.startswith("openai_codex/"):
        return model.split("/", 1)[1]
    return model


def _prompt_cache_key(system: str | None, messages: list[dict[str, Any]]) -> str:
    raw = json.dumps({"system": system or "", "messages": messages}, default=str, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _friendly_error(status_code: int, raw: str) -> str:
    if status_code == 401:
        return "OpenAI Codex OAuth token is invalid or expired. Re-run `uv run pooh-code-login`."
    if status_code == 403:
        return "OpenAI Codex access denied. Check that the account has ChatGPT Plus/Pro access."
    if status_code == 429:
        return "ChatGPT quota exceeded or rate limited. Try again later."
    if status_code in TRANSIENT_STATUS_CODES:
        return f"OpenAI Codex upstream temporarily unavailable (HTTP {status_code}). Please retry."
    return f"HTTP {status_code}: {raw}"


def _is_transient_codex_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.TransportError)):
        return True
    message = str(exc)
    if any(f"HTTP {code}" in message for code in TRANSIENT_STATUS_CODES):
        return True
    transient_markers = (
        "upstream connect error",
        "connection timeout",
        "temporarily unavailable",
        "server disconnected without sending a response",
    )
    return any(marker in message.lower() for marker in transient_markers)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def login_main() -> int:
    parser = argparse.ArgumentParser(
        description="Login to OpenAI Codex with ChatGPT Plus/Pro OAuth."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Only verify whether a cached OAuth token is available.",
    )
    args = parser.parse_args()
    try:
        token = (
            ensure_openai_codex_auth(interactive=False)
            if args.check
            else refresh_openai_codex_auth(interactive=True)
        )
    except Exception as exc:
        print(f"OpenAI Codex auth failed: {exc}", file=sys.stderr)
        return 1

    account_id = getattr(token, "account_id", "")
    if args.check:
        print(f"OpenAI Codex token is available for account {account_id}")
    else:
        print(f"Authenticated with OpenAI Codex for account {account_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(login_main())
