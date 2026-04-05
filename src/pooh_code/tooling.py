from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

from .models import ToolSpec
from .paths import PROJECT_ROOT


MAX_TOOL_OUTPUT = 40000


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[truncated, total_chars={len(text)}]"


def _safe_project_path(raw: str) -> Path:
    base = PROJECT_ROOT.resolve()
    target = (base / raw).resolve() if not os.path.isabs(raw) else Path(raw).resolve()
    if not str(target).startswith(str(base)):
        raise ValueError(f"path escapes project root: {raw}")
    return target


class ToolRegistry:
    def __init__(
        self,
        *,
        readonly: bool = False,
        enable_subagents: bool = False,
        spawn_agent_callback: Callable[..., str] | None = None,
    ) -> None:
        self._handlers: dict[str, Callable[..., Any]] = {}
        self._specs: list[ToolSpec] = []
        self.readonly = readonly
        self.enable_subagents = enable_subagents
        self.spawn_agent_callback = spawn_agent_callback
        self._register_defaults()

    def _register(self, spec: ToolSpec, handler: Callable[..., Any]) -> None:
        self._specs.append(spec)
        self._handlers[spec.name] = handler

    def register_tool(self, spec: ToolSpec, handler: Callable[..., Any]) -> None:
        self._register(spec, handler)

    def specs(self) -> list[dict[str, Any]]:
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in self._specs
        ]

    def names(self) -> list[str]:
        return [spec.name for spec in self._specs]

    def execute(self, name: str, payload: dict[str, Any]) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            return f"Unknown tool: {name}"
        try:
            result = handler(**payload)
        except Exception as exc:
            return f"Tool {name} failed: {exc}"
        if not isinstance(result, str):
            result = json.dumps(result, ensure_ascii=False, default=str, indent=2)
        return _truncate(result)

    def _register_defaults(self) -> None:
        self._register(
            ToolSpec(
                name="bash",
                description="Run a shell command inside the current project.",
                input_schema={
                    "type": "object",
                    "required": ["command"],
                    "properties": {
                        "command": {"type": "string"},
                        "cwd": {"type": "string"},
                        "timeout": {"type": "integer"},
                    },
                },
            ),
            self._bash,
        )
        self._register(
            ToolSpec(
                name="read_file",
                description="Read a file from the project.",
                input_schema={
                    "type": "object",
                    "required": ["path"],
                    "properties": {
                        "path": {"type": "string"},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                    },
                },
            ),
            self._read_file,
        )
        if not self.readonly:
            self._register(
                ToolSpec(
                    name="write_file",
                    description="Create or overwrite a file in the project.",
                    input_schema={
                        "type": "object",
                        "required": ["path", "content"],
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string"},
                        },
                    },
                ),
                self._write_file,
            )
            self._register(
                ToolSpec(
                    name="edit_file",
                    description="Replace text inside a file.",
                    input_schema={
                        "type": "object",
                        "required": ["path", "old_text", "new_text"],
                        "properties": {
                            "path": {"type": "string"},
                            "old_text": {"type": "string"},
                            "new_text": {"type": "string"},
                            "replace_all": {"type": "boolean"},
                        },
                    },
                ),
                self._edit_file,
            )
        self._register(
            ToolSpec(
                name="list_dir",
                description="List files under a directory.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                },
            ),
            self._list_dir,
        )
        self._register(
            ToolSpec(
                name="glob",
                description="Find files matching a glob pattern.",
                input_schema={
                    "type": "object",
                    "required": ["pattern"],
                    "properties": {
                        "pattern": {"type": "string"},
                    },
                },
            ),
            self._glob,
        )
        self._register(
            ToolSpec(
                name="grep",
                description="Search file contents using ripgrep.",
                input_schema={
                    "type": "object",
                    "required": ["pattern"],
                    "properties": {
                        "pattern": {"type": "string"},
                        "path": {"type": "string"},
                    },
                },
            ),
            self._grep,
        )
        self._register(
            ToolSpec(
                name="web_fetch",
                description="Fetch and summarize a web page.",
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string"},
                    },
                },
            ),
            self._web_fetch,
        )
        self._register(
            ToolSpec(
                name="web_search",
                description="Search the web for a query.",
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string"},
                        "max_results": {"type": "integer"},
                    },
                },
            ),
            self._web_search,
        )
        if self.enable_subagents and self.spawn_agent_callback is not None:
            self._register(
                ToolSpec(
                    name="spawn_agent",
                    description=(
                        "Launch a subagent for a bounded task. Prefer agent_type=explorer "
                        "for code search and repository analysis to save the main agent context."
                    ),
                    input_schema={
                        "type": "object",
                        "required": ["description", "prompt"],
                        "properties": {
                            "description": {"type": "string"},
                            "prompt": {"type": "string"},
                            "agent_type": {
                                "type": "string",
                                "enum": ["explorer", "general"],
                            },
                        },
                    },
                ),
                self.spawn_agent_callback,
            )

    def _bash(self, command: str, cwd: str = ".", timeout: int = 120) -> str:
        if self.readonly:
            lowered = command.lower()
            denied_tokens = [
                " rm ",
                " mv ",
                " cp ",
                " chmod ",
                " chown ",
                " mkdir ",
                " touch ",
                " tee ",
                ">>",
                ">",
                "git add",
                "git commit",
                "npm install",
                "pnpm install",
                "yarn add",
                "pip install",
                "uv add",
            ]
            padded = f" {lowered} "
            if any(token in padded or token in command for token in denied_tokens):
                raise ValueError("readonly bash mode blocks mutating commands")
        workdir = _safe_project_path(cwd)
        completed = subprocess.run(
            command,
            cwd=workdir,
            shell=True,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        return json.dumps(
            {
                "command": command,
                "cwd": str(workdir),
                "returncode": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
            ensure_ascii=False,
            indent=2,
        )

    def _read_file(
        self, path: str, start_line: int | None = None, end_line: int | None = None
    ) -> str:
        file_path = _safe_project_path(path)
        text = file_path.read_text(encoding="utf-8")
        if start_line or end_line:
            lines = text.splitlines()
            start = max((start_line or 1) - 1, 0)
            end = end_line or len(lines)
            selected = lines[start:end]
            return "\n".join(
                f"{index + start + 1:>5}  {line}" for index, line in enumerate(selected)
            )
        return text

    def _write_file(self, path: str, content: str) -> str:
        file_path = _safe_project_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} chars to {file_path}"

    def _edit_file(
        self, path: str, old_text: str, new_text: str, replace_all: bool = False
    ) -> str:
        file_path = _safe_project_path(path)
        text = file_path.read_text(encoding="utf-8")
        count = text.count(old_text)
        if count == 0:
            return "old_text not found"
        if replace_all:
            updated = text.replace(old_text, new_text)
            replacements = count
        else:
            updated = text.replace(old_text, new_text, 1)
            replacements = 1
        file_path.write_text(updated, encoding="utf-8")
        return f"updated {file_path}; replacements={replacements}"

    def _list_dir(self, path: str = ".") -> str:
        dir_path = _safe_project_path(path)
        items = []
        for child in sorted(dir_path.iterdir()):
            suffix = "/" if child.is_dir() else ""
            items.append(child.name + suffix)
        return "\n".join(items)

    def _glob(self, pattern: str) -> str:
        matches = sorted(
            str(path.relative_to(PROJECT_ROOT))
            for path in PROJECT_ROOT.glob(pattern)
            if path.is_file()
        )
        return "\n".join(matches[:500]) or "(no matches)"

    def _grep(self, pattern: str, path: str = ".") -> str:
        search_root = _safe_project_path(path)
        command = [
            "rg",
            "-n",
            "--hidden",
            "--glob",
            "!.git",
            pattern,
            str(search_root),
        ]
        completed = subprocess.run(command, text=True, capture_output=True)
        output = completed.stdout.strip() or completed.stderr.strip()
        return output or "(no matches)"

    def _web_fetch(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("only http/https URLs are allowed")
        response = httpx.get(url, timeout=20.0, follow_redirects=True)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines())
        text = "\n".join(line for line in text.splitlines() if line)
        return _truncate(text, 12000)

    def _web_search(self, query: str, max_results: int = 5) -> str:
        results = []
        with DDGS() as ddgs:
            for item in ddgs.text(query, max_results=max_results):
                results.append(
                    {
                        "title": item.get("title", ""),
                        "href": item.get("href", ""),
                        "body": item.get("body", ""),
                    }
                )
        return json.dumps(results, ensure_ascii=False, indent=2)
