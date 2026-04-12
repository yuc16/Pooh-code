from __future__ import annotations

from pathlib import Path

from .paths import WORKPLACE_DIR


OUTPUT_DIR = WORKPLACE_DIR / "output"
DELIVERABLE_SUFFIXES = {".docx", ".pptx", ".xlsx"}


def _is_hidden(path: Path, *, root: Path = OUTPUT_DIR) -> bool:
    rel = path.relative_to(root)
    return any(part.startswith(".") for part in rel.parts)


def is_deliverable_output_path(path: Path, *, root: Path = OUTPUT_DIR) -> bool:
    return path.is_file() and not _is_hidden(path, root=root) and path.suffix.lower() in DELIVERABLE_SUFFIXES


def iter_deliverable_files(*, root: Path = OUTPUT_DIR) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        (path for path in root.rglob("*") if is_deliverable_output_path(path, root=root)),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def session_output_dir(session_id: str, *, root: Path = OUTPUT_DIR) -> Path:
    return root / session_id


def ensure_session_output_dir(session_id: str, *, root: Path = OUTPUT_DIR) -> Path:
    target = session_output_dir(session_id, root=root)
    target.mkdir(parents=True, exist_ok=True)
    return target
