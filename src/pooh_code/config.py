from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .paths import CONFIG_DIR, PROJECT_ROOT, ensure_runtime_dirs


DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.json"
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"


@dataclass
class FeishuConfig:
    enabled: bool = True
    app_id: str = ""
    app_secret: str = ""
    domain: str = "feishu"
    bot_open_id: str = ""


@dataclass
class AgentConfig:
    name: str = "pooh-code"
    model: str = "gpt-5.4"
    max_turns: int = 8
    context_window: int = 258000
    feishu: FeishuConfig = field(default_factory=FeishuConfig)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["project_root"] = str(PROJECT_ROOT)
        return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def default_settings() -> AgentConfig:
    return AgentConfig(feishu=FeishuConfig(enabled=True, domain="feishu"))


def ensure_settings_file() -> Path:
    ensure_runtime_dirs()
    if not DEFAULT_SETTINGS_PATH.exists():
        DEFAULT_SETTINGS_PATH.write_text(
            json.dumps(default_settings().to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return DEFAULT_SETTINGS_PATH


def load_settings(path: Path | None = None) -> AgentConfig:
    ensure_settings_file()
    load_dotenv(DEFAULT_ENV_PATH, override=False)
    settings_path = path or DEFAULT_SETTINGS_PATH
    raw = default_settings().to_dict()
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            raw = _deep_merge(raw, data)
        except Exception:
            pass

    env_overrides = {
        "model": os.getenv("MODEL_ID") or os.getenv("OPENAI_CODEX_MODEL"),
        "feishu": {
            "app_id": os.getenv("FEISHU_APP_ID"),
            "app_secret": os.getenv("FEISHU_APP_SECRET"),
            "domain": os.getenv("FEISHU_DOMAIN"),
            "bot_open_id": os.getenv("FEISHU_BOT_OPEN_ID"),
        },
    }
    raw = _deep_merge(raw, env_overrides)
    feishu = raw.get("feishu", {})
    return AgentConfig(
        name=raw.get("name", "pooh-code"),
        model=raw.get("model", "gpt-5.4"),
        max_turns=int(raw.get("max_turns", 8)),
        context_window=int(raw.get("context_window", 258000)),
        feishu=FeishuConfig(
            enabled=bool(feishu.get("enabled", True)),
            app_id=feishu.get("app_id", "") or "",
            app_secret=feishu.get("app_secret", "") or "",
            domain=feishu.get("domain", "feishu") or "feishu",
            bot_open_id=feishu.get("bot_open_id", "") or "",
        ),
    )
