from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import SESSIONS_DIR, ensure_runtime_dirs


def _safe_name(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return digest


class SessionStore:
    def __init__(self, agent_id: str = "main") -> None:
        ensure_runtime_dirs()
        self.agent_id = agent_id
        self.base_dir = SESSIONS_DIR / agent_id
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "sessions.json"
        self._index = self._load_index()

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            return json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_index(self) -> None:
        self.index_path.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _session_dir(self, session_key: str) -> Path:
        return self.base_dir / _safe_name(session_key)

    def _transcript_path(self, session_key: str) -> Path:
        return self._session_dir(session_key) / "transcript.jsonl"

    def ensure_session(self, session_key: str, label: str = "") -> str:
        if session_key in self._index:
            return self._index[session_key]["session_id"]
        session_id = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        self._session_dir(session_key).mkdir(parents=True, exist_ok=True)
        self._index[session_key] = {
            "session_id": session_id,
            "label": label,
            "created_at": now,
            "last_active": now,
            "message_count": 0,
            "last_usage": None,
        }
        self._save_index()
        self._transcript_path(session_key).touch()
        return session_id

    def get_session_id(self, session_key: str) -> str:
        return self.ensure_session(session_key)

    def append_message(self, session_key: str, role: str, content: Any) -> None:
        self.ensure_session(session_key)
        record = {
            "type": role,
            "content": content,
            "ts": time.time(),
        }
        with open(self._transcript_path(session_key), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        meta = self._index[session_key]
        meta["last_active"] = datetime.now(timezone.utc).isoformat()
        meta["message_count"] += 1
        self._save_index()

    def clear_session(self, session_key: str) -> str:
        self.ensure_session(session_key)
        session_id = uuid.uuid4().hex[:12]
        self._transcript_path(session_key).write_text("", encoding="utf-8")
        meta = self._index[session_key]
        meta["session_id"] = session_id
        meta["last_active"] = datetime.now(timezone.utc).isoformat()
        meta["message_count"] = 0
        meta["last_usage"] = None
        self._save_index()
        return session_id

    def replace_messages(self, session_key: str, messages: list[dict[str, Any]]) -> None:
        self.ensure_session(session_key)
        path = self._transcript_path(session_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            for message in messages:
                record = {
                    "type": message.get("role", "user"),
                    "content": message.get("content", ""),
                    "ts": time.time(),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        meta = self._index[session_key]
        meta["last_active"] = datetime.now(timezone.utc).isoformat()
        meta["message_count"] = len(messages)
        meta["last_usage"] = None
        self._save_index()

    def get_last_usage(self, session_key: str) -> dict[str, Any] | None:
        self.ensure_session(session_key)
        return self._index.get(session_key, {}).get("last_usage")

    def set_last_usage(self, session_key: str, usage: dict[str, Any] | None) -> None:
        self.ensure_session(session_key)
        self._index[session_key]["last_usage"] = usage
        self._index[session_key]["last_active"] = datetime.now(timezone.utc).isoformat()
        self._save_index()

    def invalidate_last_usage(self, session_key: str) -> None:
        self.set_last_usage(session_key, None)

    def list_sessions(self) -> list[dict[str, Any]]:
        items = []
        for key, meta in self._index.items():
            items.append({"session_key": key, **meta})
        items.sort(key=lambda item: item["last_active"], reverse=True)
        return items

    def load_messages(self, session_key: str) -> list[dict[str, Any]]:
        self.ensure_session(session_key)
        path = self._transcript_path(session_key)
        if not path.exists():
            return []
        messages: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            role = record.get("type")
            if role not in {"user", "assistant", "system"}:
                continue
            messages.append({"role": role, "content": record.get("content", "")})
        return messages
