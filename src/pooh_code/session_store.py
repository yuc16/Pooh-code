from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from .paths import SESSIONS_DIR, ensure_runtime_dirs
from .time_utils import normalize_to_shanghai_iso, shanghai_now_iso


def _safe_name(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return digest


def _session_group(session_key: str) -> str:
    parts = session_key.split(":", 4)
    if len(parts) >= 3 and parts[2].strip():
        return parts[2].strip()
    return "unknown"


class SessionStore:
    def __init__(self, agent_id: str = "main") -> None:
        ensure_runtime_dirs()
        self.agent_id = agent_id
        self.base_dir = SESSIONS_DIR / agent_id
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.base_dir / "sessions.json"
        self._index = self._load_index()
        self._migrate_session_dirs()
        self._migrate_transcripts()

    def _load_index(self) -> dict[str, dict[str, Any]]:
        if not self.index_path.exists():
            return {}
        try:
            raw_index = json.loads(self.index_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(raw_index, dict):
            return {}

        now = shanghai_now_iso()
        index: dict[str, dict[str, Any]] = {}
        changed = False
        for session_key, raw_slot in raw_index.items():
            slot, slot_changed = self._normalize_slot(session_key, raw_slot, now)
            index[session_key] = slot
            changed = changed or slot_changed
        if changed:
            self._index = index
            self._save_index()
        return index

    def _normalize_slot(
        self,
        session_key: str,
        raw_slot: Any,
        now: str,
    ) -> tuple[dict[str, Any], bool]:
        changed = False

        # Migrate the old one-session-per-slot structure into the new layout.
        if isinstance(raw_slot, dict) and "sessions" not in raw_slot:
            session_id = str(raw_slot.get("session_id") or uuid.uuid4().hex[:12])
            session_meta = self._normalize_session_meta(
                {
                    "session_id": session_id,
                    "label": raw_slot.get("label", ""),
                    "created_at": raw_slot.get("created_at", now),
                    "last_active": raw_slot.get("last_active", raw_slot.get("created_at", now)),
                    "message_count": raw_slot.get("message_count", 0),
                    "last_usage": raw_slot.get("last_usage"),
                },
                now,
            )
            slot = {
                "label": raw_slot.get("label", ""),
                "active_session_id": session_id,
                "sessions": {session_id: session_meta},
            }
            return slot, True

        if not isinstance(raw_slot, dict):
            slot = self._create_slot(label="", now=now)
            return slot, True

        raw_sessions = raw_slot.get("sessions")
        normalized_sessions: dict[str, dict[str, Any]] = {}
        if isinstance(raw_sessions, dict):
            for raw_session_id, raw_meta in raw_sessions.items():
                meta = self._normalize_session_meta(raw_meta, now, fallback_session_id=raw_session_id)
                normalized_sessions[meta["session_id"]] = meta
                if meta["session_id"] != raw_session_id:
                    changed = True

        if not normalized_sessions:
            fallback_session_id = str(raw_slot.get("active_session_id") or uuid.uuid4().hex[:12])
            normalized_sessions[fallback_session_id] = self._normalize_session_meta(
                {
                    "session_id": fallback_session_id,
                    "label": raw_slot.get("label", ""),
                    "created_at": now,
                    "last_active": now,
                    "message_count": 0,
                    "last_usage": None,
                },
                now,
            )
            changed = True

        active_session_id = str(raw_slot.get("active_session_id") or "")
        if active_session_id not in normalized_sessions:
            active_session_id = next(iter(normalized_sessions))
            changed = True

        slot = {
            "label": raw_slot.get("label", ""),
            "active_session_id": active_session_id,
            "sessions": normalized_sessions,
        }
        return slot, changed

    def _normalize_session_meta(
        self,
        raw_meta: Any,
        now: str,
        *,
        fallback_session_id: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(raw_meta, dict):
            raw_meta = {}
        session_id = str(raw_meta.get("session_id") or fallback_session_id or uuid.uuid4().hex[:12])
        created_at, _ = normalize_to_shanghai_iso(raw_meta.get("created_at", now))
        last_active, _ = normalize_to_shanghai_iso(raw_meta.get("last_active", created_at))
        return {
            "session_id": session_id,
            "label": raw_meta.get("label", ""),
            "created_at": created_at,
            "last_active": last_active,
            "message_count": int(raw_meta.get("message_count", 0) or 0),
            "last_usage": raw_meta.get("last_usage"),
        }

    def _save_index(self) -> None:
        self.index_path.write_text(
            json.dumps(self._index, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _legacy_session_dir(self, session_key: str) -> Path:
        return self.base_dir / _safe_name(session_key)

    def _flat_session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    def _group_dir(self, session_key: str) -> Path:
        return self.base_dir / _session_group(session_key)

    def _session_dir(self, session_key: str, session_id: str) -> Path:
        return self._group_dir(session_key) / session_id

    def _transcript_path(self, session_key: str, session_id: str | None = None) -> Path:
        actual_session_id = session_id or self.get_session_id(session_key)
        return self._session_dir(session_key, actual_session_id) / "transcript.jsonl"

    def _create_session_meta(self, *, label: str = "", now: str | None = None) -> dict[str, Any]:
        actual_now = now or shanghai_now_iso()
        session_id = uuid.uuid4().hex[:12]
        return {
            "session_id": session_id,
            "label": label,
            "created_at": actual_now,
            "last_active": actual_now,
            "message_count": 0,
            "last_usage": None,
        }

    def _create_slot(self, *, label: str = "", now: str | None = None) -> dict[str, Any]:
        meta = self._create_session_meta(label=label, now=now)
        return {
            "label": label,
            "active_session_id": meta["session_id"],
            "sessions": {meta["session_id"]: meta},
        }

    def _get_slot(self, session_key: str, label: str = "") -> dict[str, Any]:
        slot = self._index.get(session_key)
        if isinstance(slot, dict) and slot.get("sessions"):
            return slot
        now = shanghai_now_iso()
        slot = self._create_slot(label=label, now=now)
        self._index[session_key] = slot
        self._ensure_session_dir(session_key, slot["active_session_id"])
        self._save_index()
        return slot

    def _active_session_meta(self, session_key: str) -> dict[str, Any]:
        slot = self._get_slot(session_key)
        active_session_id = slot["active_session_id"]
        return slot["sessions"][active_session_id]

    def _ensure_session_dir(self, session_key: str, session_id: str) -> None:
        session_dir = self._session_dir(session_key, session_id)
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "transcript.jsonl").touch(exist_ok=True)

    def _migrate_session_dirs(self) -> None:
        changed = False
        for session_key, slot in self._index.items():
            if not isinstance(slot, dict):
                continue
            legacy_dir = self._legacy_session_dir(session_key)
            for session_id in slot.get("sessions", {}):
                target_dir = self._session_dir(session_key, session_id)
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                flat_dir = self._flat_session_dir(session_id)
                legacy_transcript = legacy_dir / "transcript.jsonl"
                flat_transcript = flat_dir / "transcript.jsonl"
                target_transcript = target_dir / "transcript.jsonl"

                if flat_dir.exists() and flat_dir != target_dir:
                    if not target_dir.exists():
                        flat_dir.rename(target_dir)
                        changed = True
                    elif flat_transcript.exists() and not target_transcript.exists():
                        target_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(flat_transcript), str(target_transcript))
                        if not any(flat_dir.iterdir()):
                            flat_dir.rmdir()
                        changed = True

                if legacy_dir.exists() and legacy_dir != target_dir:
                    if not target_dir.exists():
                        legacy_dir.rename(target_dir)
                        changed = True
                    elif legacy_transcript.exists() and not target_transcript.exists():
                        target_dir.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(legacy_transcript), str(target_transcript))
                        if not any(legacy_dir.iterdir()):
                            legacy_dir.rmdir()
                        changed = True

                self._ensure_session_dir(session_key, session_id)
        if changed:
            self._save_index()

    def _migrate_transcripts(self) -> None:
        for transcript_path in self.base_dir.rglob("transcript.jsonl"):
            changed = False
            lines_out: list[str] = []
            try:
                lines = transcript_path.read_text(encoding="utf-8").splitlines()
            except Exception:
                continue
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    lines_out.append(line)
                    continue
                if isinstance(record, dict):
                    normalized, did_change = normalize_to_shanghai_iso(record.get("ts"))
                    if did_change and normalized != record.get("ts"):
                        record["ts"] = normalized
                        changed = True
                lines_out.append(json.dumps(record, ensure_ascii=False))
            if changed:
                transcript_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8")

    def ensure_session(self, session_key: str, label: str = "") -> str:
        slot = self._get_slot(session_key, label=label)
        active_session_id = slot["active_session_id"]
        self._ensure_session_dir(session_key, active_session_id)
        return active_session_id

    def get_session_id(self, session_key: str) -> str:
        return self.ensure_session(session_key)

    def new_session(self, session_key: str, label: str = "") -> str:
        slot = self._get_slot(session_key, label=label)
        meta = self._create_session_meta(label=label)
        session_id = meta["session_id"]
        slot["sessions"][session_id] = meta
        slot["active_session_id"] = session_id
        self._ensure_session_dir(session_key, session_id)
        self._save_index()
        return session_id

    def switch_session(self, session_id_prefix: str, session_key: str | None = None) -> tuple[str, str]:
        prefix = session_id_prefix.strip()
        if not prefix:
            raise ValueError("usage: /switch <session_id_prefix>")
        matches: list[tuple[str, str]] = []
        keys = [session_key] if session_key else list(self._index.keys())
        for key in keys:
            slot = self._get_slot(key) if session_key else self._index.get(key)
            if not isinstance(slot, dict):
                continue
            for session_id in slot.get("sessions", {}):
                if session_id.startswith(prefix):
                    matches.append((key, session_id))
        if not matches:
            raise ValueError(f"no session matches prefix: {prefix}")
        if len(matches) > 1:
            raise ValueError(
                "multiple sessions match prefix: "
                + ", ".join(f"{matched_id} ({matched_key})" for matched_key, matched_id in matches)
            )
        target_session_key, session_id = matches[0]
        slot = self._get_slot(target_session_key)
        slot["active_session_id"] = session_id
        slot["sessions"][session_id]["last_active"] = shanghai_now_iso()
        self._ensure_session_dir(target_session_key, session_id)
        self._save_index()
        return target_session_key, session_id

    def append_message(self, session_key: str, role: str, content: Any) -> None:
        session_id = self.ensure_session(session_key)
        record = {
            "type": role,
            "content": content,
            "ts": shanghai_now_iso(),
        }
        with open(self._transcript_path(session_key, session_id), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        meta = self._active_session_meta(session_key)
        meta["last_active"] = shanghai_now_iso()
        meta["message_count"] += 1
        self._save_index()

    def clear_session(self, session_key: str) -> str:
        session_id = self.ensure_session(session_key)
        self._transcript_path(session_key, session_id).write_text("", encoding="utf-8")
        meta = self._active_session_meta(session_key)
        meta["last_active"] = shanghai_now_iso()
        meta["message_count"] = 0
        meta["last_usage"] = None
        self._save_index()
        return session_id

    def replace_messages(self, session_key: str, messages: list[dict[str, Any]]) -> None:
        session_id = self.ensure_session(session_key)
        path = self._transcript_path(session_key, session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            for message in messages:
                record = {
                    "type": message.get("role", "user"),
                    "content": message.get("content", ""),
                    "ts": shanghai_now_iso(),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        meta = self._active_session_meta(session_key)
        meta["last_active"] = shanghai_now_iso()
        meta["message_count"] = len(messages)
        meta["last_usage"] = None
        self._save_index()

    def get_last_usage(self, session_key: str) -> dict[str, Any] | None:
        return self._active_session_meta(session_key).get("last_usage")

    def set_last_usage(self, session_key: str, usage: dict[str, Any] | None) -> None:
        meta = self._active_session_meta(session_key)
        meta["last_usage"] = usage
        meta["last_active"] = shanghai_now_iso()
        self._save_index()

    def invalidate_last_usage(self, session_key: str) -> None:
        self.set_last_usage(session_key, None)

    def list_sessions(self, session_key: str | None = None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        keys = [session_key] if session_key else list(self._index.keys())
        for key in keys:
            slot = self._get_slot(key) if session_key else self._index.get(key)
            if not isinstance(slot, dict):
                continue
            active_session_id = slot.get("active_session_id")
            for session_id, meta in slot.get("sessions", {}).items():
                if not isinstance(meta, dict):
                    continue
                items.append(
                    {
                        "session_key": key,
                        "active": session_id == active_session_id,
                        **meta,
                    }
                )
        items.sort(key=lambda item: (item["active"], item["last_active"]), reverse=True)
        return items

    def load_messages(self, session_key: str) -> list[dict[str, Any]]:
        session_id = self.ensure_session(session_key)
        path = self._transcript_path(session_key, session_id)
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
