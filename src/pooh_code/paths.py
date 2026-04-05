from __future__ import annotations

from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent
SRC_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = SRC_DIR.parent
WORKPLACE_DIR = PROJECT_ROOT / "workplace"
RUNTIME_DIR = WORKPLACE_DIR / "runtime"
CONFIG_DIR = RUNTIME_DIR / "config"
SESSIONS_DIR = RUNTIME_DIR / "sessions"
SKILLS_DIR = RUNTIME_DIR / "skills"
MEMORY_DIR = RUNTIME_DIR / "memory"
LOGS_DIR = RUNTIME_DIR / "logs"
TASKS_DIR = RUNTIME_DIR / "tasks"
CACHE_DIR = RUNTIME_DIR / "cache"

BOOTSTRAP_FILES = [
    "SOUL.md",
    "IDENTITY.md",
    "TOOLS.md",
    "USER.md",
    "BOOTSTRAP.md",
    "AGENTS.md",
    "MEMORY.md",
]


def ensure_runtime_dirs() -> None:
    for path in [
        WORKPLACE_DIR,
        RUNTIME_DIR,
        CONFIG_DIR,
        SESSIONS_DIR,
        SKILLS_DIR,
        MEMORY_DIR,
        LOGS_DIR,
        TASKS_DIR,
        CACHE_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)
