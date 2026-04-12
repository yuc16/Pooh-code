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
import sys
import threading
import time
import traceback
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
from pooh_code.commands import CommandProcessor  # noqa: E402
from pooh_code.config import load_settings  # noqa: E402
from pooh_code.output_files import (  # noqa: E402
    delete_session_output_dir,
    OUTPUT_DIR,
    group_output_files_by_session,
    is_visible_output_path,
    iter_deliverable_files,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
WEB_CHANNEL = "web"
WEB_ACCOUNT = "local"
WEB_PEER = "web-user"

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
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


def _extract_text_only(content: Any) -> str:
    """Extract only the text parts from content, ignoring tool blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = str(block.get("text", ""))
                if text:
                    chunks.append(text)
            elif not isinstance(block, dict):
                chunks.append(str(block))
        return "\n".join(chunks)
    return json.dumps(content, ensure_ascii=False, default=str)


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
            out.append({"role": role, "text": text})
            continue

        if role == "assistant":
            text = _extract_text_only(content)
            tools = _extract_tool_blocks(content)
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
            if paired:
                entry["tools"] = paired
            out.append(entry)
            continue

        out.append({"role": role, "text": _extract_text_only(content)})
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
        return self.server.agent.build_session_key(WEB_CHANNEL, WEB_ACCOUNT, WEB_PEER)

    def _session_id_from_query(self, parsed: Any) -> str | None:
        qs = parse_qs(parsed.query)
        raw = (qs.get("session_id") or [""])[0].strip()
        return raw or None

    def _session_id_from_body(self, body: dict[str, Any], session_key: str) -> str:
        raw = str(body.get("session_id", "")).strip()
        return raw or self.server.agent.sessions.get_session_id(session_key)

    # ---------- routing ----------
    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
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
            if path == "/" or path == "/index.html":
                return self._serve_static("index.html")
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/") :])
            self._send_error_json(404, f"not found: {path}")
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            self._send_error_json(500, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/api/chat":
                return self._handle_chat()
            if path == "/api/chat/stream":
                return self._handle_chat_stream()
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
            if path == "/api/session/compact":
                return self._handle_compact_session()
            self._send_error_json(404, f"not found: {path}")
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
        return {
            "session_key": session_key,
            "session_id": actual_session_id,
            "model": agent.config.model,
            "context_window": agent.config.context_window,
            "running": self.server.runs.is_running(actual_session_id),
            "usage": {
                "tokens": usage.tokens,
                "limit": usage.limit,
                "display": usage.display,
            },
        }

    def _handle_state(self) -> None:
        parsed = urlparse(self.path)
        self._send_json({"ok": True, **self._state_payload(self._session_id_from_query(parsed))})

    def _handle_messages(self) -> None:
        parsed = urlparse(self.path)
        agent = self.server.agent
        session_key = self._session_key()
        session_id = self._session_id_from_query(parsed) or agent.sessions.get_session_id(session_key)
        messages = agent.sessions.load_messages(session_key, session_id=session_id)
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
        for item in items:
            item["running"] = self.server.runs.is_running(item["session_id"])
        self._send_json({"ok": True, "sessions": items, **self._state_payload()})

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
        if not text:
            raise ValueError("text is required")
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

        def on_event(kind: str, payload: dict[str, Any]) -> None:
            _write_sse(kind, payload)

        try:
            agent.ask_stream(
                session_key,
                text,
                on_event,
                session_id=session_id,
                cancel_event=run.cancel_event,
            )
            _write_sse("state", self._state_payload(session_id))
        except concurrent.futures.CancelledError:
            _write_sse("cancelled", {"session_id": session_id})
        except Exception as exc:
            traceback.print_exc()
            _write_sse("error", {"error": str(exc)})
        finally:
            self.server.runs.finish(run)

        if not closed["v"]:
            try:
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

    def _handle_files(self) -> None:
        """列出 workplace/output/ 中的文件，支持浏览和下载。"""
        groups = group_output_files_by_session()
        self._send_json(
            {
                "ok": True,
                "groups": groups,
                "deliverable_files": [
                    {
                        "path": str(f.relative_to(OUTPUT_DIR)),
                        "name": f.name,
                        "suffix": f.suffix.lower(),
                    }
                    for f in iter_deliverable_files()
                ],
                **self._state_payload(),
            }
        )

    def _handle_download(self, parsed: Any) -> None:
        """下载 workplace/output/ 中的文件。"""
        qs = parse_qs(parsed.query)
        rel_path = (qs.get("path") or [""])[0].strip()
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
            _content_disposition_attachment(target.name),
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

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
