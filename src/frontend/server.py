"""Lightweight HTTP server exposing PoohAgent to a web frontend.

Run it with:

    uv run python -m frontend.server

Or (from the project root, so imports resolve):

    PYTHONPATH=src uv run python -m frontend.server
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import mimetypes
import re
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

# Ensure the sibling package `pooh_code` is importable when this file is run
# directly (e.g. `python src/frontend/server.py`).
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from pooh_code.agent import PoohAgent  # noqa: E402
from pooh_code.auth_db import AuthError, User, get_store  # noqa: E402
from pooh_code.commands import COMMAND_CATALOG, TOOL_DESCRIPTION_MAP, CommandProcessor  # noqa: E402
from pooh_code.config import load_settings  # noqa: E402
from pooh_code.image_generation import generate_images  # noqa: E402
from pooh_code.output_files import (  # noqa: E402
    delete_session_output_dir,
    OUTPUT_DIR,
    group_output_files_by_session,
    is_visible_output_path,
    iter_deliverable_files,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "workplace" / "uploads"
WEB_CHANNEL = "web"
WEB_ACCOUNT = "user"  # 固定前缀；真正的隔离来自 user_id
AUTH_COOKIE = "pooh_token"
SSE_TEXT_BATCH_WINDOW = 0.06
SSE_TEXT_BATCH_CHARS = 160
SSE_REASONING_BATCH_WINDOW = 0.12
SSE_REASONING_BATCH_CHARS = 320
AUTH_EXEMPT_PATHS = {
    "/", "/index.html", "/login", "/login.html",
    "/api/auth/login", "/api/auth/register", "/api/auth/me", "/api/auth/logout",
}

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
}

# 文件下载支持的 MIME 类型
DOWNLOAD_MIME_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".py": "text/x-python; charset=utf-8",
    ".pdf": "application/pdf",
    ".csv": "text/csv; charset=utf-8",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/markdown; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".zip": "application/zip",
}


def _content_disposition_attachment(filename: str) -> str:
    try:
        ascii_name = filename.encode("ascii").decode("ascii")
    except UnicodeEncodeError:
        suffix = Path(filename).suffix
        ascii_name = f"download{suffix}" if suffix else "download"
    escaped_ascii_name = ascii_name.replace("\\", "\\\\").replace('"', '\\"')
    encoded_name = quote(filename, safe="")
    return f"attachment; filename=\"{escaped_ascii_name}\"; filename*=UTF-8''{encoded_name}"


def _content_disposition_inline(filename: str) -> str:
    try:
        ascii_name = filename.encode("ascii").decode("ascii")
    except UnicodeEncodeError:
        suffix = Path(filename).suffix
        ascii_name = f"preview{suffix}" if suffix else "preview"
    escaped_ascii_name = ascii_name.replace("\\", "\\\\").replace('"', '\\"')
    encoded_name = quote(filename, safe="")
    return f"inline; filename=\"{escaped_ascii_name}\"; filename*=UTF-8''{encoded_name}"


def _output_url(rel_path: str, *, inline: bool = False) -> str:
    encoded = quote(rel_path, safe="")
    return f"/api/download?path={encoded}{'&inline=1' if inline else ''}"


def _parse_multipart(content_type: str, body: bytes) -> list[dict[str, Any]]:
    """解析 multipart/form-data，返回 [{name, filename, data, content_type}]。"""
    m = re.search(r"boundary=([^\s;]+)", content_type)
    if not m:
        return []
    boundary = m.group(1).encode("ascii")
    parts = body.split(b"--" + boundary)
    result: list[dict[str, Any]] = []
    for part in parts:
        part = part.strip()
        if not part or part == b"--":
            continue
        if b"\r\n\r\n" in part:
            header_block, data = part.split(b"\r\n\r\n", 1)
        elif b"\n\n" in part:
            header_block, data = part.split(b"\n\n", 1)
        else:
            continue
        # 去掉结尾的 \r\n
        if data.endswith(b"\r\n"):
            data = data[:-2]
        headers_str = header_block.decode("utf-8", errors="replace")
        name_match = re.search(r'name="([^"]*)"', headers_str)
        filename_match = re.search(r'filename="([^"]*)"', headers_str)
        ct_match = re.search(r"Content-Type:\s*(.+)", headers_str, re.IGNORECASE)
        result.append({
            "name": name_match.group(1) if name_match else "",
            "filename": filename_match.group(1) if filename_match else None,
            "data": data,
            "content_type": ct_match.group(1).strip() if ct_match else "application/octet-stream",
        })
    return result


def _extract_text_only(content: Any) -> str:
    """Extract only the text parts from content, ignoring tool blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        has_image_block = any(
            isinstance(block, dict) and block.get("type") == "image"
            for block in content
        )
        has_text_block = any(
            isinstance(block, dict)
            and block.get("type") == "text"
            and str(block.get("text", "")).strip()
            for block in content
        )
        for block in content:
            if isinstance(block, dict):
                block_type = block.get("type")
                if block_type == "text":
                    text = str(block.get("text", ""))
                    if _detect_attachment_from_text(text):
                        continue
                    if has_image_block and re.match(r"^\s*🖼️\s*图片文件:", text):
                        continue
                    if text:
                        chunks.append(text)
                elif block_type == "image" and not has_text_block:
                    filename = str(block.get("filename", "")).strip()
                    if filename:
                        chunks.append(f"🖼️ 图片文件: {filename}")
                    else:
                        chunks.append("🖼️ 已上传图片")
            else:
                chunks.append(str(block))
        return "\n".join(chunks)
    return json.dumps(content, ensure_ascii=False, default=str)


def _detect_attachment_from_text(text: str) -> dict[str, Any] | None:
    value = str(text or "").strip()
    if not value:
        return None

    patterns: list[tuple[re.Pattern[str], str]] = [
        (re.compile(r"^\s*📄\s*PDF 文件:\s*(.+?)(?:\n|$)"), "pdf"),
        (re.compile(r"^\s*📄\s*Word 文档:\s*(.+?)(?:\n|$)"), "word"),
        (re.compile(r"^\s*📊\s*Excel 文件:\s*(.+?)(?:\n|$)"), "excel"),
        (re.compile(r"^\s*📊\s*(.+?\.(?:csv|tsv))(?:\n|$)", re.IGNORECASE), "table"),
        (re.compile(r"^\s*📑\s*PPT 文件:\s*(.+?)(?:\n|$)"), "ppt"),
        (re.compile(r"^\s*📝\s*(.+?\.(?:txt|md|json|py|js|ts|html|css|xml|yaml|yml|toml|sh|sql|log))(?:\n|$)", re.IGNORECASE), "text"),
        (re.compile(r"^\s*\[已上传文件:\s*(.+?)（"), "file"),
    ]
    for pattern, subtype in patterns:
        match = pattern.match(value)
        if not match:
            continue
        name = Path(match.group(1).strip()).name
        if not name:
            continue
        return {
            "kind": "file",
            "subtype": subtype,
            "name": name,
        }
    return None


def _extract_attachments(content: Any) -> list[dict[str, Any]]:
    if not isinstance(content, list):
        return []
    items: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") != "image":
            if block.get("type") == "text":
                attachment = _detect_attachment_from_text(str(block.get("text", "")))
                if attachment:
                    items.append(attachment)
            continue
        media_type = str(block.get("media_type", "")).strip() or "image/png"
        name = str(block.get("filename", "")).strip() or "已上传图片"
        if str(block.get("path", "")).strip():
            rel_path = str(block.get("path", "")).strip()
            items.append(
                {
                    "kind": "image",
                    "name": name,
                    "media_type": media_type,
                    "size": int(block.get("size") or 0),
                    "url": _output_url(rel_path, inline=True),
                }
            )
            continue
        data = str(block.get("data", "")).strip()
        if not data:
            continue
        items.append(
            {
                "kind": "image",
                "name": name,
                "media_type": media_type,
                "url": f"data:{media_type};base64,{data}",
            }
        )
    return items


def _extract_tool_blocks(content: Any) -> list[dict[str, Any]]:
    """Extract tool_use / tool_result blocks for structured rendering."""
    if not isinstance(content, list):
        return []
    blocks: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "tool_use":
            blocks.append({
                "type": "tool_use",
                "id": block.get("id", ""),
                "name": block.get("name", "tool"),
                "input": block.get("input", {}),
            })
        elif btype == "tool_result":
            raw = block.get("content", "")
            if not isinstance(raw, str):
                raw = json.dumps(raw, ensure_ascii=False, default=str)
            blocks.append({
                "type": "tool_result",
                "tool_use_id": block.get("tool_use_id", ""),
                "content": raw,
                "is_error": bool(block.get("is_error")),
            })
    return blocks


def _serialize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    # Build a lookup of tool_result by tool_use_id for pairing.
    tool_results: dict[str, dict[str, Any]] = {}
    for msg in messages:
        if msg.get("role") == "user":
            for tb in _extract_tool_blocks(msg.get("content", "")):
                if tb["type"] == "tool_result" and tb.get("tool_use_id"):
                    tool_results[tb["tool_use_id"]] = tb

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        # Skip pure tool-result user turns.
        if role == "user":
            tool_blocks = _extract_tool_blocks(content)
            text = _extract_text_only(content)
            if not text.strip() and tool_blocks:
                continue
            entry: dict[str, Any] = {"role": role, "text": text}
            if msg.get("mode"):
                entry["mode"] = msg.get("mode")
            if msg.get("model"):
                entry["model"] = msg.get("model")
            if msg.get("ts"):
                entry["ts"] = msg.get("ts")
            attachments = _extract_attachments(content)
            if attachments:
                entry["attachments"] = attachments
            out.append(entry)
            continue

        if role == "assistant":
            text = _extract_text_only(content)
            tools = _extract_tool_blocks(content)
            attachments = _extract_attachments(content)
            # Pair each tool_use with its result.
            paired: list[dict[str, Any]] = []
            for t in tools:
                if t["type"] == "tool_use":
                    result = tool_results.get(t.get("id", ""))
                    paired.append({
                        "name": t["name"],
                        "input": t["input"],
                        "result": result.get("content", "") if result else "",
                        "is_error": result.get("is_error", False) if result else False,
                    })
            entry: dict[str, Any] = {"role": role, "text": text}
            if msg.get("mode"):
                entry["mode"] = msg.get("mode")
            if msg.get("model"):
                entry["model"] = msg.get("model")
            if msg.get("ts"):
                entry["ts"] = msg.get("ts")
            if paired:
                entry["tools"] = paired
            if attachments:
                entry["attachments"] = attachments
            out.append(entry)
            continue

        entry = {"role": role, "text": _extract_text_only(content)}
        if msg.get("mode"):
            entry["mode"] = msg.get("mode")
        if msg.get("model"):
            entry["model"] = msg.get("model")
        if msg.get("ts"):
            entry["ts"] = msg.get("ts")
        out.append(entry)
    return out


class PoohFrontendHandler(BaseHTTPRequestHandler):
    agent: PoohAgent  # injected on the server instance
    commands: CommandProcessor

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        sys.stderr.write("[web] " + (format % args) + "\n")

    # ---------- response helpers ----------
    def _send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid json body: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("json body must be an object")
        return parsed

    def _session_key(self) -> str:
        user = getattr(self, "user", None)
        if user is None:
            raise PermissionError("unauthenticated")
        return self.server.agent.build_session_key(WEB_CHANNEL, WEB_ACCOUNT, f"u{user.id}")

    # ---------- auth helpers ----------
    def _read_cookie(self, name: str) -> str | None:
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            k, v = part.split("=", 1)
            if k.strip() == name:
                return v.strip()
        return None

    def _resolve_user(self) -> User | None:
        token = self._read_cookie(AUTH_COOKIE)
        return get_store().resolve_token(token) if token else None

    def _require_auth(self, path: str) -> bool:
        """返回 True 表示通过鉴权；False 表示已发送 401/重定向响应。"""
        if path in AUTH_EXEMPT_PATHS or path.startswith("/static/"):
            return True
        user = self._resolve_user()
        if user is None:
            self._send_error_json(401, "unauthenticated")
            return False
        self.user = user
        return True

    def _set_auth_cookie(self, token: str, ttl: int = 30 * 24 * 3600) -> None:
        self.send_header(
            "Set-Cookie",
            f"{AUTH_COOKIE}={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={ttl}",
        )

    def _clear_auth_cookie(self) -> None:
        self.send_header(
            "Set-Cookie",
            f"{AUTH_COOKIE}=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0",
        )

    def _session_id_from_query(self, parsed: Any) -> str | None:
        qs = parse_qs(parsed.query)
        raw = (qs.get("session_id") or [""])[0].strip()
        return raw or None

    def _session_id_from_body(self, body: dict[str, Any], session_key: str) -> str:
        raw = str(body.get("session_id", "")).strip()
        resolved = raw or self.server.agent.sessions.get_session_id(session_key)
        if raw:
            # 防止越权：必须是当前用户 session_key 下的 session_id
            owned = {it.get("session_id") for it in self.server.agent.sessions.list_sessions(session_key=session_key)}
            if resolved not in owned:
                raise PermissionError("session_id does not belong to current user")
        return resolved

    # ---------- routing ----------
    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if not self._require_auth(path):
                return
            if path == "/api/auth/me":
                return self._handle_auth_me()
            if path == "/api/state":
                return self._handle_state()
            if path == "/api/messages":
                return self._handle_messages()
            if path == "/api/sessions":
                return self._handle_sessions()
            if path == "/api/files":
                return self._handle_files()
            if path == "/api/download":
                return self._handle_download(parsed)
            if path == "/login" or path == "/login.html":
                return self._serve_static("login.html")
            if path == "/" or path == "/index.html":
                # 未登录：重定向到登录页
                if self._resolve_user() is None:
                    self.send_response(302)
                    self.send_header("Location", "/login")
                    self.end_headers()
                    return
                return self._serve_static("index.html")
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/") :])
            self._send_error_json(404, f"not found: {path}")
        except PermissionError as exc:
            self._send_error_json(403, str(exc))
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            self._send_error_json(500, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/auth/register":
                return self._handle_auth_register()
            if path == "/api/auth/login":
                return self._handle_auth_login()
            if path == "/api/auth/logout":
                return self._handle_auth_logout()
            if not self._require_auth(path):
                return
            if path == "/api/upload":
                return self._handle_upload()
            if path == "/api/chat":
                return self._handle_chat()
            if path == "/api/chat/stream":
                return self._handle_chat_stream()
            if path == "/api/image/generate":
                return self._handle_image_generate()
            if path == "/api/command":
                return self._handle_command()
            if path == "/api/session/new":
                return self._handle_new_session()
            if path == "/api/session/switch":
                return self._handle_switch_session()
            if path == "/api/session/clear":
                return self._handle_clear_session()
            if path == "/api/session/delete":
                return self._handle_delete_session()
            if path == "/api/session/cancel":
                return self._handle_cancel_session()
            if path == "/api/session/inject":
                return self._handle_inject()
            if path == "/api/session/rename":
                return self._handle_rename_session()
            if path == "/api/session/compact":
                return self._handle_compact_session()
            self._send_error_json(404, f"not found: {path}")
        except PermissionError as exc:
            self._send_error_json(403, str(exc))
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            self._send_error_json(500, str(exc))

    # ---------- static ----------
    def _serve_static(self, relpath: str) -> None:
        # Normalize and prevent path traversal.
        target = (STATIC_DIR / relpath).resolve()
        if STATIC_DIR.resolve() not in target.parents and target != STATIC_DIR.resolve():
            self._send_error_json(403, "forbidden")
            return
        if not target.exists() or not target.is_file():
            self._send_error_json(404, f"not found: {relpath}")
            return
        mime = MIME_TYPES.get(target.suffix.lower(), "application/octet-stream")
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---------- handlers ----------
    def _state_payload(self, session_id: str | None = None) -> dict[str, Any]:
        agent = self.server.agent
        session_key = self._session_key()
        actual_session_id = session_id or agent.sessions.get_session_id(session_key)
        usage = agent.get_context_usage(session_key, session_id=actual_session_id)
        tool_specs = agent.tools.specs()
        return {
            "session_key": session_key,
            "session_id": actual_session_id,
            "model": agent.config.model,
            "image_generation": {
                "model": agent.config.image.model,
                "default_aspect_ratio": agent.config.image.default_aspect_ratio,
                "enabled": bool(agent.config.image.api_key),
            },
            "context_window": agent.config.context_window,
            "running": self.server.runs.is_running(actual_session_id),
            "usage": {
                "tokens": usage.tokens,
                "limit": usage.limit,
                "display": usage.display,
            },
            "capabilities": {
                "commands": COMMAND_CATALOG,
                "tools": [
                    {
                        "name": spec.get("name", ""),
                        "description": TOOL_DESCRIPTION_MAP.get(
                            spec.get("name", ""),
                            spec.get("description", ""),
                        ),
                        "input_schema": spec.get("input_schema", {}),
                    }
                    for spec in tool_specs
                ],
                "skills": [
                    {
                        "name": skill.name,
                        "description": skill.description or "",
                    }
                    for skill in agent.skills.discover()
                ],
            },
        }

    # ---------- auth handlers ----------
    def _handle_auth_register(self) -> None:
        body = self._read_json_body()
        email = str(body.get("email", ""))
        password = str(body.get("password", ""))
        try:
            user = get_store().register(email, password)
            token = get_store().issue_token(user.id, ua=self.headers.get("User-Agent"))
        except AuthError as exc:
            return self._send_error_json(400, str(exc))
        body_out = json.dumps(
            {"ok": True, "user": {"id": user.id, "email": user.email}},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_out)))
        self.send_header("Cache-Control", "no-store")
        self._set_auth_cookie(token)
        self.end_headers()
        self.wfile.write(body_out)

    def _handle_auth_login(self) -> None:
        body = self._read_json_body()
        email = str(body.get("email", ""))
        password = str(body.get("password", ""))
        try:
            user = get_store().login(email, password)
            token = get_store().issue_token(user.id, ua=self.headers.get("User-Agent"))
        except AuthError as exc:
            return self._send_error_json(401, str(exc))
        body_out = json.dumps(
            {"ok": True, "user": {"id": user.id, "email": user.email}},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_out)))
        self.send_header("Cache-Control", "no-store")
        self._set_auth_cookie(token)
        self.end_headers()
        self.wfile.write(body_out)

    def _handle_auth_logout(self) -> None:
        token = self._read_cookie(AUTH_COOKIE)
        if token:
            get_store().revoke_token(token)
        body_out = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_out)))
        self._clear_auth_cookie()
        self.end_headers()
        self.wfile.write(body_out)

    def _handle_auth_me(self) -> None:
        user = getattr(self, "user", None) or self._resolve_user()
        if user is None:
            return self._send_error_json(401, "unauthenticated")
        self._send_json({"ok": True, "user": {"id": user.id, "email": user.email}})

    def _handle_state(self) -> None:
        parsed = urlparse(self.path)
        self._send_json({"ok": True, **self._state_payload(self._session_id_from_query(parsed))})

    def _handle_messages(self) -> None:
        parsed = urlparse(self.path)
        agent = self.server.agent
        session_key = self._session_key()
        session_id = self._session_id_from_query(parsed) or agent.sessions.get_session_id(session_key)
        messages = agent.sessions.load_messages(session_key, session_id=session_id, include_meta=True)
        self._send_json(
            {
                "ok": True,
                "messages": _serialize_messages(messages),
                **self._state_payload(session_id),
            }
        )

    def _handle_sessions(self) -> None:
        agent = self.server.agent
        session_key = self._session_key()
        # 只列出当前 web channel 下的会话，不混入 cli / feishu。
        items = agent.sessions.list_sessions(session_key=session_key)
        # 为每个 session 附带 token usage，前端会话卡片要用。
        for item in items:
            item["running"] = self.server.runs.is_running(item["session_id"])
            try:
                usage = agent.get_context_usage(session_key, session_id=item["session_id"])
                item["usage"] = {
                    "tokens": usage.tokens,
                    "limit": usage.limit,
                    "display": usage.display,
                }
            except Exception:
                item["usage"] = None
        self._send_json({"ok": True, "sessions": items, **self._state_payload()})

    def _handle_upload(self) -> None:
        """处理文件上传，保存到 workplace/uploads/ 并返回文件路径列表。"""
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._send_error_json(400, "Content-Type must be multipart/form-data")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            self._send_error_json(400, "empty body")
            return
        if length > 100 * 1024 * 1024:  # 100MB 限制
            self._send_error_json(413, "file too large (max 100MB)")
            return
        body = self.rfile.read(length)
        parts = _parse_multipart(content_type, body)
        if not parts:
            self._send_error_json(400, "no files found in request")
            return

        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        saved: list[dict[str, str]] = []
        for part in parts:
            if not part.get("filename"):
                continue
            # 用 UUID 前缀防止文件名冲突
            safe_name = Path(part["filename"]).name
            unique_name = f"{uuid.uuid4().hex[:8]}_{safe_name}"
            dest = UPLOAD_DIR / unique_name
            dest.write_bytes(part["data"])
            saved.append({
                "path": str(dest),
                "name": safe_name,
                "size": len(part["data"]),
            })

        self._send_json({"ok": True, "files": saved})

    def _handle_chat(self) -> None:
        body = self._read_json_body()
        text = str(body.get("text", "")).strip()
        if not text:
            raise ValueError("text is required")
        agent = self.server.agent
        session_key = self._session_key()
        session_id = self._session_id_from_body(body, session_key)
        run = self.server.runs.start(session_id)
        try:
            reply = agent.ask_for_session(session_key, text, session_id=session_id)
            state = self._state_payload(session_id)
            self._send_json(
                {
                    "ok": True,
                    "reply": {
                        "text": reply.text,
                        "session_id": reply.session_id,
                        "model": reply.model,
                        "compacted": reply.compacted,
                    },
                    **state,
                }
            )
        finally:
            self.server.runs.finish(run)

    def _handle_chat_stream(self) -> None:
        body = self._read_json_body()
        text = str(body.get("text", "")).strip()
        files = body.get("files") or []  # list of file path strings
        if not text and not files:
            raise ValueError("text or files is required")
        agent = self.server.agent
        session_key = self._session_key()
        session_id = self._session_id_from_body(body, session_key)
        run = self.server.runs.start(session_id)

        # Start SSE response. Force close after stream so the client's
        # reader promptly sees `done` instead of hanging on keep-alive.
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        closed = {"v": False}
        pending = {
            "text_delta": "",
            "reasoning_delta": "",
            "text_started_at": 0.0,
            "reasoning_started_at": 0.0,
        }

        def _write_sse(event_type: str, payload: dict[str, Any]) -> None:
            if closed["v"]:
                return
            data = json.dumps(
                {"type": event_type, **payload},
                ensure_ascii=False,
                default=str,
            )
            try:
                self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                closed["v"] = True

        def _flush_text_delta() -> None:
            text_buf = pending["text_delta"]
            if not text_buf:
                return
            pending["text_delta"] = ""
            pending["text_started_at"] = 0.0
            _write_sse("text_delta", {"text": text_buf})

        def _flush_reasoning_delta() -> None:
            reasoning_buf = pending["reasoning_delta"]
            if not reasoning_buf:
                return
            pending["reasoning_delta"] = ""
            pending["reasoning_started_at"] = 0.0
            _write_sse("reasoning_delta", {"text": reasoning_buf})

        def _flush_pending() -> None:
            _flush_text_delta()
            _flush_reasoning_delta()

        def on_event(kind: str, payload: dict[str, Any]) -> None:
            now = time.monotonic()

            if kind == "text_delta":
                delta = str(payload.get("text", "") or "")
                if not delta:
                    return
                if pending["text_delta"]:
                    elapsed = now - float(pending["text_started_at"] or now)
                    if elapsed >= SSE_TEXT_BATCH_WINDOW or len(pending["text_delta"]) >= SSE_TEXT_BATCH_CHARS:
                        _flush_text_delta()
                if not pending["text_delta"]:
                    pending["text_started_at"] = now
                pending["text_delta"] += delta
                if len(pending["text_delta"]) >= SSE_TEXT_BATCH_CHARS:
                    _flush_text_delta()
                return

            if kind == "reasoning_delta":
                delta = str(payload.get("text", "") or "")
                if not delta:
                    return
                if pending["reasoning_delta"]:
                    elapsed = now - float(pending["reasoning_started_at"] or now)
                    if elapsed >= SSE_REASONING_BATCH_WINDOW or len(pending["reasoning_delta"]) >= SSE_REASONING_BATCH_CHARS:
                        _flush_reasoning_delta()
                if not pending["reasoning_delta"]:
                    pending["reasoning_started_at"] = now
                pending["reasoning_delta"] += delta
                if len(pending["reasoning_delta"]) >= SSE_REASONING_BATCH_CHARS:
                    _flush_reasoning_delta()
                return

            _flush_pending()
            _write_sse(kind, payload)

        try:
            agent.ask_stream(
                session_key,
                text,
                on_event,
                session_id=session_id,
                cancel_event=run.cancel_event,
                files=files or None,
                inject_drain=run.drain_injects,
            )
            _flush_pending()
            _write_sse("state", self._state_payload(session_id))
        except concurrent.futures.CancelledError:
            _flush_pending()
            _write_sse("cancelled", {"session_id": session_id})
        except Exception as exc:
            traceback.print_exc()
            _flush_pending()
            _write_sse("error", {"error": str(exc)})
        finally:
            self.server.runs.finish(run)

        if not closed["v"]:
            try:
                _flush_pending()
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            except Exception:
                pass

    def _handle_command(self) -> None:
        body = self._read_json_body()
        text = str(body.get("text", "")).strip()
        if not text:
            raise ValueError("text is required")
        if not text.startswith("/"):
            raise ValueError("command must start with /")
        session_key = self._session_key()
        session_id = self._session_id_from_body(body, session_key)
        if self.server.runs.is_running(session_id):
            raise ValueError("session is running; cancel it before executing commands")
        # CommandProcessor is still slot-oriented; keep web active session in sync for commands.
        self.server.agent.sessions.switch_session(session_id, session_key=session_key)
        result = self.server.commands.handle(text, session_key)
        self._send_json(
            {
                "ok": True,
                "handled": result.handled,
                "text": result.text,
                "session_key": result.session_key or session_key,
                **self._state_payload(session_id),
            }
        )

    def _handle_image_generate(self) -> None:
        body = self._read_json_body()
        text = str(body.get("text", "")).strip()
        if not text:
            raise ValueError("text is required")
        agent = self.server.agent
        session_key = self._session_key()
        session_id = self._session_id_from_body(body, session_key)
        if self.server.runs.is_running(session_id):
            raise ValueError("session is running; cancel it before generating an image")

        agent.sessions.append_message(
            session_key,
            "user",
            text,
            session_id=session_id,
            mode="image_generation",
            model=agent.config.image.model,
        )
        result = generate_images(
            agent.config.image,
            prompt=text,
            session_id=session_id,
            aspect_ratio=str(body.get("aspect_ratio", "")).strip() or None,
        )

        assistant_content: list[dict[str, Any]] = []
        if result.text.strip():
            assistant_content.append({"type": "text", "text": result.text.strip()})
        for image in result.images:
            assistant_content.append(
                {
                    "type": "image",
                    "filename": image.name,
                    "media_type": image.media_type,
                    "path": image.relative_path,
                    "size": image.size,
                }
            )
        if not assistant_content:
            assistant_content = [{"type": "text", "text": "已生成图片。"}]
        agent.sessions.append_message(
            session_key,
            "assistant",
            assistant_content,
            session_id=session_id,
            mode="image_generation",
            model=result.model,
        )

        self._send_json(
            {
                "ok": True,
                "reply": {
                    "text": result.text,
                    "attachments": _extract_attachments(assistant_content),
                    "model": result.model,
                    "session_id": session_id,
                },
                **self._state_payload(session_id),
            }
        )

    def _handle_new_session(self) -> None:
        agent = self.server.agent
        session_key = self._session_key()
        new_id = agent.sessions.new_session(session_key)
        self._send_json({"ok": True, "session_id": new_id, **self._state_payload()})

    def _handle_switch_session(self) -> None:
        body = self._read_json_body()
        prefix = str(body.get("session_id_prefix", "")).strip()
        if not prefix:
            raise ValueError("session_id_prefix is required")
        agent = self.server.agent
        session_key = self._session_key()
        # 只在当前 web channel 的 slot 内切换，避免跳到 cli/feishu 的 session。
        target_key, session_id = agent.sessions.switch_session(prefix, session_key=session_key)
        self._send_json(
            {
                "ok": True,
                "session_key": target_key,
                "session_id": session_id,
                **self._state_payload(),
            }
        )

    def _handle_clear_session(self) -> None:
        body = self._read_json_body()
        agent = self.server.agent
        session_key = self._session_key()
        session_id = self._session_id_from_body(body, session_key)
        if self.server.runs.is_running(session_id):
            raise ValueError("session is running; cancel it before clearing")
        agent.sessions.clear_session(session_key, session_id=session_id)
        self._send_json({"ok": True, **self._state_payload(session_id)})

    def _handle_delete_session(self) -> None:
        body = self._read_json_body()
        session_id = str(body.get("session_id", "")).strip()
        if not session_id:
            raise ValueError("session_id is required")
        if self.server.runs.is_running(session_id):
            raise ValueError("session is running; cancel it before deleting")
        agent = self.server.agent
        session_key = self._session_key()
        active_id = agent.sessions.delete_session(session_key, session_id)
        delete_session_output_dir(session_id)
        self._send_json(
            {
                "ok": True,
                "deleted_session_id": session_id,
                "active_session_id": active_id,
                **self._state_payload(),
            }
        )

    def _handle_cancel_session(self) -> None:
        body = self._read_json_body()
        session_key = self._session_key()
        session_id = self._session_id_from_body(body, session_key)
        cancelled = self.server.runs.cancel(session_id)
        self._send_json({"ok": True, "session_id": session_id, "cancelled": cancelled, **self._state_payload(session_id)})

    def _owned_session_ids(self) -> set[str]:
        session_key = self._session_key()
        try:
            return {
                item["session_id"]
                for item in self.server.agent.sessions.list_sessions(session_key=session_key)
            }
        except Exception:
            return set()

    def _handle_files(self) -> None:
        """列出 workplace/output/ 中的文件；只返回当前用户拥有的 session 对应的分组。"""
        session_key = self._session_key()
        owned_ids = self._owned_session_ids()
        session_labels = {}
        try:
            for item in self.server.agent.sessions.list_sessions(session_key=session_key):
                session_labels[item["session_id"]] = item.get("label", "")
        except Exception:
            pass
        groups = [g for g in group_output_files_by_session() if g.get("session_id") in owned_ids]
        for group in groups:
            group["label"] = session_labels.get(group["session_id"], "")
        # deliverable_files 只保留落在用户自己 session 目录下的
        deliverables = []
        for f in iter_deliverable_files():
            rel = f.relative_to(OUTPUT_DIR)
            sid = rel.parts[0] if rel.parts else ""
            if sid in owned_ids:
                deliverables.append({
                    "path": str(rel),
                    "name": f.name,
                    "suffix": f.suffix.lower(),
                })
        self._send_json(
            {
                "ok": True,
                "groups": groups,
                "deliverable_files": deliverables,
                **self._state_payload(),
            }
        )

    def _handle_download(self, parsed: Any) -> None:
        """下载 workplace/output/ 中的文件；要求文件位于当前用户拥有的 session 目录下。"""
        qs = parse_qs(parsed.query)
        rel_path = (qs.get("path") or [""])[0].strip()
        inline = (qs.get("inline") or [""])[0].strip() in {"1", "true", "yes"}
        if not rel_path:
            self._send_error_json(400, "path parameter is required")
            return
        # 防止路径穿越
        target = (OUTPUT_DIR / rel_path).resolve()
        if not str(target).startswith(str(OUTPUT_DIR.resolve())):
            self._send_error_json(403, "forbidden: path traversal")
            return
        if not target.exists() or not target.is_file():
            self._send_error_json(404, f"not found: {rel_path}")
            return
        # 越权校验：文件必须在当前用户某个 session 的目录下
        try:
            relative_parts = target.relative_to(OUTPUT_DIR.resolve()).parts
        except ValueError:
            relative_parts = ()
        owner_sid = relative_parts[0] if relative_parts else ""
        if owner_sid not in self._owned_session_ids():
            self._send_error_json(403, "forbidden: session does not belong to current user")
            return
        if not is_visible_output_path(target):
            self._send_error_json(403, f"unsupported download type: {target.suffix.lower()}")
            return
        mime = DOWNLOAD_MIME_TYPES.get(target.suffix.lower())
        if not mime:
            guessed, _ = mimetypes.guess_type(target.name)
            mime = guessed or "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header(
            "Content-Disposition",
            _content_disposition_inline(target.name) if inline else _content_disposition_attachment(target.name),
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _handle_inject(self) -> None:
        body = self._read_json_body()
        session_id = str(body.get("session_id", "")).strip()
        text = str(body.get("text", "")).strip()
        if not session_id or not text:
            raise ValueError("session_id and text are required")
        if not self.server.runs.is_running(session_id):
            raise ValueError("session is not running; send a normal message instead")
        self.server.runs.inject(session_id, text)
        self._send_json({"ok": True, "session_id": session_id})

    def _handle_rename_session(self) -> None:
        body = self._read_json_body()
        session_id = str(body.get("session_id", "")).strip()
        label = str(body.get("label", "")).strip()
        if not session_id:
            raise ValueError("session_id is required")
        agent = self.server.agent
        session_key = self._session_key()
        agent.sessions.set_label(session_key, label, session_id=session_id)
        self._send_json({"ok": True, "session_id": session_id, "label": label, **self._state_payload()})

    def _handle_compact_session(self) -> None:
        body = self._read_json_body()
        agent = self.server.agent
        session_key = self._session_key()
        session_id = self._session_id_from_body(body, session_key)
        if self.server.runs.is_running(session_id):
            raise ValueError("session is running; cancel it before compacting")
        did = agent.compact_session(session_key, force=True, session_id=session_id)
        self._send_json({"ok": True, "compacted": did, **self._state_payload(session_id)})


class PoohFrontendServer(ThreadingHTTPServer):
    agent: PoohAgent
    commands: CommandProcessor
    runs: "RunRegistry"


class SessionRun:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.started_at = time.time()
        self.cancel_event = threading.Event()
        self.inject_queue: list[str] = []  # 用户插话消息队列
        self._inject_lock = threading.Lock()

    def push_inject(self, text: str) -> None:
        with self._inject_lock:
            self.inject_queue.append(text)

    def drain_injects(self) -> list[str]:
        with self._inject_lock:
            msgs = list(self.inject_queue)
            self.inject_queue.clear()
            return msgs


class RunRegistry:
    def __init__(self) -> None:
        self._runs: dict[str, SessionRun] = {}
        self._lock = threading.Lock()

    def start(self, session_id: str) -> SessionRun:
        with self._lock:
            if session_id in self._runs:
                raise ValueError(f"session {session_id} is already running")
            run = SessionRun(session_id)
            self._runs[session_id] = run
            return run

    def finish(self, run: SessionRun) -> None:
        with self._lock:
            current = self._runs.get(run.session_id)
            if current is run:
                self._runs.pop(run.session_id, None)

    def cancel(self, session_id: str) -> bool:
        with self._lock:
            run = self._runs.get(session_id)
            if not run:
                return False
            run.cancel_event.set()
            return True

    def is_running(self, session_id: str) -> bool:
        with self._lock:
            return session_id in self._runs

    def inject(self, session_id: str, text: str) -> bool:
        with self._lock:
            run = self._runs.get(session_id)
            if not run:
                return False
            run.push_inject(text)
            return True

    def get_run(self, session_id: str) -> SessionRun | None:
        with self._lock:
            return self._runs.get(session_id)


def build_server(host: str, port: int, *, config_path: Path | None = None) -> PoohFrontendServer:
    settings = load_settings(path=config_path)
    agent = PoohAgent(settings)
    commands = CommandProcessor(agent)
    server = PoohFrontendServer((host, port), PoohFrontendHandler)
    server.agent = agent
    server.commands = commands
    server.runs = RunRegistry()
    return server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pooh-frontend")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--config", default=None, help="Path to settings.json")
    args = parser.parse_args(argv)

    config_path = Path(args.config) if args.config else None
    server = build_server(args.host, args.port, config_path=config_path)
    url = f"http://{args.host}:{args.port}"
    print(f"pooh-code frontend ready at {url}")
    print("press Ctrl-C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
