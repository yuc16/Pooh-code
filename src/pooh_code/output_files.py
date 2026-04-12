from __future__ import annotations

import shutil
from pathlib import Path

from .paths import WORKPLACE_DIR


OUTPUT_DIR = WORKPLACE_DIR / "output"
DELIVERABLE_SUFFIXES = {".docx", ".pptx", ".xlsx"}


def _is_hidden(path: Path, *, root: Path = OUTPUT_DIR) -> bool:
    rel = path.relative_to(root)
    return any(part.startswith(".") for part in rel.parts)


def is_visible_output_path(path: Path, *, root: Path = OUTPUT_DIR) -> bool:
    return path.is_file() and not _is_hidden(path, root=root)


def is_deliverable_output_path(path: Path, *, root: Path = OUTPUT_DIR) -> bool:
    return is_visible_output_path(path, root=root) and path.suffix.lower() in DELIVERABLE_SUFFIXES


def iter_output_files(*, root: Path = OUTPUT_DIR) -> list[Path]:
    if not root.exists():
        return []
    return sorted(
        (path for path in root.rglob("*") if is_visible_output_path(path, root=root)),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )


def iter_deliverable_files(*, root: Path = OUTPUT_DIR) -> list[Path]:
    return [path for path in iter_output_files(root=root) if is_deliverable_output_path(path, root=root)]


def group_output_files_by_session(*, root: Path = OUTPUT_DIR) -> list[dict[str, object]]:
    groups: dict[str, dict[str, object]] = {}
    for path in iter_output_files(root=root):
        rel = path.relative_to(root)
        session_id = rel.parts[0] if len(rel.parts) > 1 else "(ungrouped)"
        stat = path.stat()
        group = groups.setdefault(
            session_id,
            {
                "session_id": session_id,
                "path": session_id,
                "file_count": 0,
                "latest_modified": 0.0,
                "files": [],
            },
        )
        group["file_count"] = int(group["file_count"]) + 1
        group["latest_modified"] = max(float(group["latest_modified"]), stat.st_mtime)
        group["files"].append(
            {
                "path": str(rel),
                "name": path.name,
                "relative_path": str(rel.relative_to(session_id)) if session_id != "(ungrouped)" and len(rel.parts) > 1 else str(rel),
                "size": stat.st_size,
                "modified": stat.st_mtime,
                "suffix": path.suffix.lower(),
                "downloadable": True,
            }
        )
    return sorted(groups.values(), key=lambda item: (item["latest_modified"], item["session_id"]), reverse=True)


def session_output_dir(session_id: str, *, root: Path = OUTPUT_DIR) -> Path:
    return root / session_id


def ensure_session_output_dir(session_id: str, *, root: Path = OUTPUT_DIR) -> Path:
    target = session_output_dir(session_id, root=root)
    target.mkdir(parents=True, exist_ok=True)
    return target


def delete_session_output_dir(session_id: str, *, root: Path = OUTPUT_DIR) -> None:
    target = session_output_dir(session_id, root=root)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
