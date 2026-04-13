from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .paths import CONFIG_DIR, PROJECT_ROOT, ensure_runtime_dirs


DEFAULT_SETTINGS_PATH = CONFIG_DIR / "settings.json"


@dataclass
class FeishuConfig:
    enabled: bool = True
    app_id: str = ""
    app_secret: str = ""
    domain: str = "feishu"
    bot_open_id: str = ""


@dataclass
class ReasoningConfig:
    effort: str = "medium"   # low / medium / high
    summary: str = "auto"    # auto / concise / detailed / none


@dataclass
class SearchConfig:
    tavily_api_key: str = ""
    brave_api_key: str = ""


@dataclass
class AgentConfig:
    name: str = "pooh-code"
    model: str = "Qwen3.5-397B-A17B"
    max_turns: int = 8
    context_window: int = 131072
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)
    search: SearchConfig = field(default_factory=SearchConfig)

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


def _apply_env_from_settings(cfg: AgentConfig) -> None:
    """把 settings.json 里的敏感/运行时配置同步到 os.environ，
    让依赖环境变量的旧模块（tooling.py / openai_codex.py）无需改造即可读到。"""
    if cfg.search.tavily_api_key:
        os.environ["TAVILY_API_KEY"] = cfg.search.tavily_api_key
    if cfg.search.brave_api_key:
        os.environ["BRAVE_API_KEY"] = cfg.search.brave_api_key
    if cfg.reasoning.effort:
        os.environ["OPENAI_CODEX_REASONING_EFFORT"] = cfg.reasoning.effort
    if cfg.reasoning.summary:
        os.environ["OPENAI_CODEX_REASONING_SUMMARY"] = cfg.reasoning.summary


def load_settings(path: Path | None = None) -> AgentConfig:
    ensure_settings_file()
    settings_path = path or DEFAULT_SETTINGS_PATH
    raw = default_settings().to_dict()
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            raw = _deep_merge(raw, data)
        except Exception:
            pass

    feishu = raw.get("feishu", {})
    reasoning = raw.get("reasoning", {})
    search = raw.get("search", {})
    cfg = AgentConfig(
        name=raw.get("name", "pooh-code"),
        model=raw.get("model", "Qwen3.5-397B-A17B"),
        max_turns=int(raw.get("max_turns", 8)),
        context_window=int(raw.get("context_window", 131072)),
        feishu=FeishuConfig(
            enabled=bool(feishu.get("enabled", True)),
            app_id=feishu.get("app_id", "") or "",
            app_secret=feishu.get("app_secret", "") or "",
            domain=feishu.get("domain", "feishu") or "feishu",
            bot_open_id=feishu.get("bot_open_id", "") or "",
        ),
        reasoning=ReasoningConfig(
            effort=reasoning.get("effort", "medium") or "medium",
            summary=reasoning.get("summary", "auto") or "auto",
        ),
        search=SearchConfig(
            tavily_api_key=search.get("tavily_api_key", "") or "",
            brave_api_key=search.get("brave_api_key", "") or "",
        ),
    )
    _apply_env_from_settings(cfg)
    return cfg
