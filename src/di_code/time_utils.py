from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SHANGHAI_TZ_NAME = "Asia/Shanghai"


def shanghai_now() -> datetime:
    return datetime.now(SHANGHAI_TZ)


def shanghai_now_iso() -> str:
    return shanghai_now().isoformat()


def shanghai_iso_from_epoch(value: float | int) -> str:
    return datetime.fromtimestamp(float(value), SHANGHAI_TZ).isoformat()


def normalize_to_shanghai_iso(value: Any) -> tuple[Any, bool]:
    if isinstance(value, (int, float)):
        return shanghai_iso_from_epoch(value), True
    if not isinstance(value, str):
        return value, False

    raw = value.strip()
    if not raw:
        return value, False

    candidate = raw.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.fromtimestamp(float(raw), SHANGHAI_TZ)
        except ValueError:
            return value, False
        return parsed.isoformat(), True

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=SHANGHAI_TZ).isoformat(), True
    return parsed.astimezone(SHANGHAI_TZ).isoformat(), True
