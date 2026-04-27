from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, ClassVar
from urllib.parse import urlparse

import logging
import re

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from duckduckgo_search import DDGS

from .models import ToolSpec
from .paths import CACHE_DIR, WORKPLACE_DIR

logger = logging.getLogger(__name__)

MAX_TOOL_OUTPUT = 40000
_PAPER_RESULT_TYPES = {"article", "preprint", "review", "book-chapter", "book", "dissertation"}
_PAPER_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "in", "into", "is",
    "of", "on", "or", "the", "to", "with",
}


def _find_uv_path() -> str | None:
    uv_path = shutil.which("uv")
    if uv_path:
        return str(Path(uv_path).resolve())
    candidates = [
        Path.home() / ".local/bin/uv",
        Path("/root/.local/bin/uv"),
        Path("/usr/local/bin/uv"),
        Path("/usr/bin/uv"),
        Path("/bin/uv"),
    ]
    for candidate in candidates:
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
    return None


def _get_tavily_key() -> str:
    return os.getenv("TAVILY_API_KEY", "")


def _get_brave_key() -> str:
    return os.getenv("BRAVE_API_KEY", "")


def _get_bocha_key() -> str:
    return os.getenv("BOCHA_API_KEY", "")


def _get_search1api_key() -> str:
    return os.getenv("SEARCH1API_KEY", "")


def _get_exa_key() -> str:
    return os.getenv("EXA_API_KEY", "")


def _get_jina_key() -> str:
    return os.getenv("JINA_API_KEY", "")


def _get_openalex_key() -> str:
    return os.getenv("OPENALEX_API_KEY", "")


_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
_BOCHA_SEARCH_URL = "https://api.bochaai.com/v1/web-search"
_SEARCH1API_URL = "https://api.search1api.com/search"
_EXA_SEARCH_URL = "https://api.exa.ai/search"
_JINA_READER_URL = "https://r.jina.ai/"
_JINA_DEEPSEARCH_URL = "https://deepsearch.jina.ai/v1/chat/completions"
_OPENALEX_WORKS_URL = "https://api.openalex.org/works"


def _is_chinese_query(query: str) -> bool:
    """判断 query 是否以中文为主：CJK 字符占比 >= 30% 视为中文。"""
    if not query:
        return False
    total = sum(1 for ch in query if not ch.isspace())
    if total == 0:
        return False
    cjk = sum(1 for ch in query if "一" <= ch <= "鿿")
    return cjk / total >= 0.3


def _is_neural_query(query: str) -> bool:
    """是否适合语义/神经搜索：明确想找"类似/相关"内容时偏好 Exa。"""
    q = query.lower()
    triggers = (
        "similar to", "like this", "find papers", "related work",
        "类似", "相关研究", "相关论文", "类似的博客", "类似的文章",
    )
    return any(t in q for t in triggers)


def _is_news_query(query: str) -> bool:
    """是否是时效性查询：明显的"最新/新闻/年份"信号 → 偏好 Tavily news + Brave + Bocha。"""
    q = query.lower()
    triggers = ("新闻", "最新", "今日", "今天", "本周", "近期", "news", "latest", "today", "breaking")
    if any(t in q for t in triggers):
        return True
    # 含明显年份（2024-2027）也视为偏时效
    return bool(re.search(r"\b20(2[4-9]|3\d)\b", q))

# 需要移除的非正文标签
_STRIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "aside", "iframe", "svg"}
# 常见正文容器的 CSS 选择器（按优先级排列）
_ARTICLE_SELECTORS = ["article", "main", "[role='main']", ".post-content", ".article-content", ".entry-content", ".content"]


def _truncate(text: str, limit: int = MAX_TOOL_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n[truncated, total_chars={len(text)}]"


def _safe_workplace_path(raw: str) -> Path:
    """把相对/绝对路径约束在 workplace 沙箱内，越界抛错。"""
    base = WORKPLACE_DIR.resolve()
    normalized = raw.strip()
    if normalized == "workplace" or normalized == "workplace/":
        normalized = "."
    elif normalized.startswith("workplace/"):
        normalized = normalized[len("workplace/") :]
    target = Path(normalized) if os.path.isabs(normalized) else base / normalized
    target = target.resolve()
    try:
        target.relative_to(base)
    except ValueError as exc:
        raise ValueError(f"path escapes workplace sandbox: {raw}") from exc
    return target


_SANDBOX_PROFILE_TEMPLATE = """(version 1)
(allow default)
(deny file-write*)
(allow file-write*
    (subpath "{workplace}")
    (subpath "/tmp")
    (subpath "/private/tmp")
    (subpath "/private/var/folders")
    (subpath "/var/folders")
    (literal "/dev/null")
    (literal "/dev/dtracehelper")
    (literal "/dev/tty")
    (literal "/dev/stdout")
    (literal "/dev/stderr"))
"""


@lru_cache(maxsize=1)
def _bwrap_available() -> bool:
    return shutil.which("bwrap") is not None


@lru_cache(maxsize=1)
def _linux_bwrap_usable() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return False
    workplace = str(WORKPLACE_DIR.resolve())
    project_root = str(WORKPLACE_DIR.parent.resolve())
    uv_path = _find_uv_path()
    uv_mount: list[str] = []
    if uv_path:
        uv_parent = str(Path(uv_path).resolve().parent.parent)
        uv_mount = ["--ro-bind-try", uv_parent, uv_parent]
    try:
        probe = subprocess.run(
            [
                bwrap,
                "--ro-bind", "/usr", "/usr",
                "--ro-bind-try", "/bin", "/bin",
                "--ro-bind-try", "/sbin", "/sbin",
                "--ro-bind-try", "/lib", "/lib",
                "--ro-bind-try", "/lib64", "/lib64",
                "--tmpfs", "/etc",
                "--dir", "/etc/ssl",
                "--ro-bind-try", "/etc/ssl/certs", "/etc/ssl/certs",
                "--ro-bind-try", "/etc/ca-certificates", "/etc/ca-certificates",
                "--ro-bind-try", "/etc/resolv.conf", "/etc/resolv.conf",
                "--ro-bind-try", "/etc/hosts", "/etc/hosts",
                "--ro-bind-try", "/etc/nsswitch.conf", "/etc/nsswitch.conf",
                "--ro-bind-try", project_root, project_root,
                *uv_mount,
                "--bind", workplace, workplace,
                "--proc", "/proc",
                "--dev", "/dev",
                "--share-net",
                "/bin/sh", "-c", "true",
            ],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except Exception:
        return False
    return probe.returncode == 0


def _build_sandboxed_bash(command: str, chdir: Path) -> tuple[list[str] | str, bool]:
    """按平台选择沙箱实现：

    - macOS → sandbox-exec + 自定义 profile(B 层)
    - Linux + bwrap 可用 → bubblewrap 新 mount namespace(B 层)
    - Linux + bwrap 不可用 → 直接拒绝执行（fail-closed）
    - 其他 → 原样执行,只有 A 层(路径校验 + cwd 约束)

    返回 (argv_or_str, use_shell)。
    """
    workplace = str(WORKPLACE_DIR.resolve())

    if sys.platform == "darwin":
        profile = _SANDBOX_PROFILE_TEMPLATE.format(workplace=workplace)
        return ["sandbox-exec", "-p", profile, "/bin/sh", "-c", command], False

    if sys.platform.startswith("linux") and _linux_bwrap_usable():
        # bwrap 创建新 mount namespace:
        # - /usr /bin /sbin /lib /lib64 /etc 只读绑定(系统工具链)
        # - 仅挂载运行命令所需的最小 /etc 文件(不暴露整个 /etc)
        # - 项目根目录只读绑定(保证 uv / .venv / pyproject 可见)
        # - workplace 读写绑定
        # - /tmp 用私有 tmpfs 隔离
        # - 保留网络(--share-net),方便 web_search/pip 等
        project_root = str(WORKPLACE_DIR.parent.resolve())
        uv_path = _find_uv_path()
        uv_mount: list[str] = []
        if uv_path:
            uv_parent = str(Path(uv_path).resolve().parent.parent)
            uv_mount = ["--ro-bind-try", uv_parent, uv_parent]
        return [
            "bwrap",
            "--ro-bind", "/usr", "/usr",
            "--ro-bind-try", "/bin", "/bin",
            "--ro-bind-try", "/sbin", "/sbin",
            "--ro-bind-try", "/lib", "/lib",
            "--ro-bind-try", "/lib64", "/lib64",
            "--tmpfs", "/etc",
            "--dir", "/etc/ssl",
            "--ro-bind-try", "/etc/ssl/certs", "/etc/ssl/certs",
            "--ro-bind-try", "/etc/ca-certificates", "/etc/ca-certificates",
            "--ro-bind-try", "/etc/resolv.conf", "/etc/resolv.conf",
            "--ro-bind-try", "/etc/hosts", "/etc/hosts",
            "--ro-bind-try", "/etc/nsswitch.conf", "/etc/nsswitch.conf",
            "--ro-bind-try", project_root, project_root,
            *uv_mount,
            "--bind", workplace, workplace,
            "--tmpfs", "/tmp",
            "--proc", "/proc",
            "--dev", "/dev",
            "--unshare-user-try",
            "--unshare-pid",
            "--share-net",
            "--die-with-parent",
            "--chdir", str(chdir),
            "/bin/sh", "-c", command,
        ], False

    if sys.platform.startswith("linux"):
        raise RuntimeError(
            "Linux sandbox requires bubblewrap (bwrap) with usable user namespace support. "
            "Install bubblewrap and ensure bwrap can start successfully, otherwise bash is blocked."
        )

    return command, True


def _tool_env() -> dict[str, str]:
    env = os.environ.copy()
    path_entries = [entry for entry in env.get("PATH", "").split(os.pathsep) if entry]
    uv_path = _find_uv_path()
    if uv_path:
        uv_dir = str(Path(uv_path).resolve().parent)
        if uv_dir not in path_entries:
            path_entries.insert(0, uv_dir)
    env["PATH"] = os.pathsep.join(path_entries)
    # Force uv to use a project-local writable cache instead of ~/.cache/uv,
    # which is blocked in the agent sandbox and may not exist on servers.
    uv_cache_dir = CACHE_DIR / "uv"
    uv_cache_dir.mkdir(parents=True, exist_ok=True)
    env["UV_CACHE_DIR"] = str(uv_cache_dir)
    return env


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

    def register_tool(self, spec: ToolSpec, handler: Callable[..., Any], *, replace: bool = False) -> None:
        if replace:
            self._specs = [existing for existing in self._specs if existing.name != spec.name]
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
                        "confirmed": {
                            "type": "boolean",
                            "description": (
                                "高危命令（rm -r、rm *、find -delete 等）需要用户二次确认。"
                                "首次调用不要设置此字段，拿到拦截提示后，"
                                "必须先把命令内容和风险告知用户并获得明确同意，"
                                "然后再以 confirmed=true 重新调用。"
                            ),
                        },
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
                description=(
                    "Fetch a web page and return clean markdown of its main content. "
                    "Backed by Jina Reader (handles SPA / JS-rendered pages well), "
                    "with a BeautifulSoup fallback if Jina is unavailable. "
                    "Use when you already have a specific URL."
                ),
                input_schema={
                    "type": "object",
                    "required": ["url"],
                    "properties": {
                        "url": {"type": "string", "description": "The URL to fetch."},
                    },
                },
            ),
            self._web_fetch,
        )
        self._register(
            ToolSpec(
                name="web_search",
                description=(
                    "Search the web with smart multi-engine routing. In auto mode the engines are "
                    "picked by query intent — Chinese queries → Bocha + Tavily; semantic / "
                    "'similar to / find papers' → Exa + Tavily; news / latest → Tavily + Brave + "
                    "Bocha; default → Tavily + Brave + Exa. Results are URL-deduplicated and "
                    "cross-engine consensus is boosted to the top. Each result carries a `source` "
                    "label (e.g. `tavily+brave`). Falls back to DuckDuckGo if everything else fails."
                ),
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "description": "Search query string."},
                        "max_results": {
                            "type": "integer",
                            "description": "Number of merged results (default 8, max 15).",
                        },
                        "engine": {
                            "type": "string",
                            "enum": [
                                "auto", "tavily", "brave", "bocha", "exa",
                                "search1api", "duckduckgo",
                            ],
                            "description": (
                                "auto = smart routing (default). Or pin to one: "
                                "tavily(answers/general), brave(独立索引), bocha(中文站), "
                                "exa(neural/语义), search1api(Google 元搜索), duckduckgo(兜底)."
                            ),
                        },
                        "search_depth": {
                            "type": "string",
                            "enum": ["basic", "advanced"],
                            "description": "Tavily-only: advanced for deeper quality (default basic).",
                        },
                    },
                },
            ),
            self._web_search,
        )
        self._register(
            ToolSpec(
                name="deep_research",
                description=(
                    "Run a deep, iterative research loop on a question. Backed by Jina DeepSearch "
                    "(search → read → reason cycles, returns a cited answer with visited URLs). "
                    "If Jina is unavailable, falls back to multi-engine search + Jina Reader on "
                    "the top results. Use this for open-ended research questions where snippets "
                    "from web_search are not enough — replaces the old web_search_and_read."
                ),
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Research question (full sentence, not just keywords).",
                        },
                        "reasoning_effort": {
                            "type": "string",
                            "enum": ["low", "medium", "high"],
                            "description": "Jina DeepSearch reasoning depth (default medium).",
                        },
                        "max_pages": {
                            "type": "integer",
                            "description": "Fallback path: how many top pages to fetch (default 4, max 6).",
                        },
                    },
                },
            ),
            self._deep_research,
        )
        self._register(
            ToolSpec(
                name="paper_search",
                description=(
                    "Search scholarly papers via OpenAlex and return structured metadata "
                    "such as title, authors, year, venue, DOI, citations, open-access links, "
                    "and abstract snippets. Prefer this over generic web search for论文/文献/参考文献 tasks."
                ),
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Paper search query, e.g. topic keywords, title, DOI, or question phrase.",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Number of papers to return (default 8, max 15).",
                        },
                        "from_year": {
                            "type": "integer",
                            "description": "Optional lower bound of publication year.",
                        },
                        "to_year": {
                            "type": "integer",
                            "description": "Optional upper bound of publication year.",
                        },
                        "open_access_only": {
                            "type": "boolean",
                            "description": "If true, only return papers marked as open access.",
                        },
                        "sort": {
                            "type": "string",
                            "enum": ["relevance", "cited_by_count", "publication_year"],
                            "description": "Sort strategy. Default relevance.",
                        },
                    },
                },
            ),
            self._paper_search,
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

    _DANGEROUS_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        re.compile(r"\brm\b.*\s-[^\s]*r"),      # rm -r / rm -rf / rm -fr
        re.compile(r"\brm\b.*\*"),               # rm *.xxx / rm dir/*
        re.compile(r"\bfind\b.*-delete\b"),       # find ... -delete
        re.compile(r"\bfind\b.*-exec\s+rm\b"),    # find ... -exec rm
        re.compile(r"\brm\b\s+-rf?\s+/"),         # rm -r / or rm -rf /
    ]

    def _is_dangerous(self, command: str) -> bool:
        lowered = command.lower()
        return any(pat.search(lowered) for pat in self._DANGEROUS_PATTERNS)

    def _bash(self, command: str, cwd: str = ".", timeout: int = 120, confirmed: bool = False) -> str:
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

        if not confirmed and self._is_dangerous(command):
            return (
                f"⚠️ 高危命令被拦截，未执行：\n"
                f"  {command}\n\n"
                f"请将此命令及其潜在影响告知用户，获得明确同意后，"
                f"以 confirmed=true 重新调用。"
            )

        workdir = _safe_workplace_path(cwd)
        argv, use_shell = _build_sandboxed_bash(command, workdir)
        completed = subprocess.run(
            argv,
            cwd=workdir,
            shell=use_shell,
            text=True,
            capture_output=True,
            timeout=timeout,
            env=_tool_env(),
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
        file_path = _safe_workplace_path(path)
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
        file_path = _safe_workplace_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"wrote {len(content)} chars to {file_path}"

    def _edit_file(
        self, path: str, old_text: str, new_text: str, replace_all: bool = False
    ) -> str:
        file_path = _safe_workplace_path(path)
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
        dir_path = _safe_workplace_path(path)
        items = []
        for child in sorted(dir_path.iterdir()):
            suffix = "/" if child.is_dir() else ""
            items.append(child.name + suffix)
        return "\n".join(items)

    def _glob(self, pattern: str) -> str:
        matches = sorted(
            str(path.relative_to(WORKPLACE_DIR))
            for path in WORKPLACE_DIR.glob(pattern)
            if path.is_file()
        )
        return "\n".join(matches[:500]) or "(no matches)"

    def _grep(self, pattern: str, path: str = ".") -> str:
        search_root = _safe_workplace_path(path)
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

    # ── web: fetch ──────────────────────────────────────────────

    def _web_fetch(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("only http/https URLs are allowed")
        return _fetch_and_extract(url)

    # ── web: search ─────────────────────────────────────────────

    def _web_search(
        self,
        query: str,
        max_results: int = 8,
        engine: str = "auto",
        search_depth: str = "basic",
    ) -> str:
        max_results = min(max(max_results, 1), 15)
        results = _search_dispatch(query, max_results, engine, search_depth)
        meta = {
            "query": query,
            "engine_requested": engine,
            "engines_used": sorted({r.get("source", "") for r in results if r.get("source")}),
            "count": len(results),
            "results": results,
        }
        return json.dumps(meta, ensure_ascii=False, indent=2)

    # ── web: deep research ─────────────────────────────────────

    def _deep_research(
        self,
        query: str,
        reasoning_effort: str = "medium",
        max_pages: int = 4,
    ) -> str:
        """优先用 Jina DeepSearch（迭代式 search→read→reason）；
        没 key 或失败时，回退到 多引擎搜索 + Jina Reader 抓 top N 篇正文。"""
        if reasoning_effort not in {"low", "medium", "high"}:
            reasoning_effort = "medium"
        max_pages = min(max(max_pages, 1), 6)

        if _get_jina_key():
            try:
                ds = _jina_deepsearch(query, reasoning_effort=reasoning_effort)
                payload = {
                    "mode": "jina_deepsearch",
                    "query": query,
                    "reasoning_effort": reasoning_effort,
                    "answer": ds.get("answer", ""),
                    "visited_urls": ds.get("visited_urls", []),
                    "usage": ds.get("usage", {}),
                }
                return _truncate(json.dumps(payload, ensure_ascii=False, indent=2))
            except Exception as exc:
                logger.warning("jina deepsearch failed: %s; falling back to search+read", exc)

        # Fallback：多引擎搜索 → 取 top max_pages → Jina Reader 抓全文
        search_results = _search_dispatch(query, max_pages, "auto", "advanced")
        output_parts: list[str] = [
            f"# Deep Research（fallback：search + read）\n查询：{query}\n"
        ]
        for i, item in enumerate(search_results[:max_pages]):
            url = item.get("url") or ""
            title = item.get("title", "")
            snippet = item.get("content") or ""
            source = item.get("source", "")
            section = f"\n## [{i+1}] {title}\nURL: {url}\nSource: {source}\n"
            if snippet:
                section += f"摘要: {snippet}\n"
            try:
                full_text = _fetch_and_extract(url, limit=6000)
                section += f"\n--- 正文 ---\n{full_text}\n"
            except Exception as exc:
                section += f"\n(抓取失败: {exc})\n"
            output_parts.append(section)

        return _truncate("\n".join(output_parts))

    # ── papers: OpenAlex ────────────────────────────────────────

    def _paper_search(
        self,
        query: str,
        max_results: int = 8,
        from_year: int | None = None,
        to_year: int | None = None,
        open_access_only: bool = False,
        sort: str = "relevance",
    ) -> str:
        max_results = min(max(max_results, 1), 15)
        candidate_count = min(max(max_results * 4, 15), 25)
        params: dict[str, Any] = {
            "search": query,
            "per-page": candidate_count,
            "select": ",".join(
                [
                    "id",
                    "display_name",
                    "publication_year",
                    "publication_date",
                    "doi",
                    "type",
                    "cited_by_count",
                    "open_access",
                    "authorships",
                    "primary_location",
                    "best_oa_location",
                    "abstract_inverted_index",
                ]
            ),
        }
        filters: list[str] = []
        if from_year is not None:
            filters.append(f"from_publication_date:{int(from_year)}-01-01")
        if to_year is not None:
            filters.append(f"to_publication_date:{int(to_year)}-12-31")
        if open_access_only:
            filters.append("is_oa:true")
        if filters:
            params["filter"] = ",".join(filters)
        if sort == "cited_by_count":
            params["sort"] = "cited_by_count:desc"
        elif sort == "publication_year":
            params["sort"] = "publication_year:desc"
        openalex_key = _get_openalex_key()
        if openalex_key:
            params["api_key"] = openalex_key

        headers = {
            "User-Agent": "pooh-code (python; scholarly search via OpenAlex)",
            "Accept": "application/json",
        }
        response = httpx.get(_OPENALEX_WORKS_URL, params=params, headers=headers, timeout=30.0)
        response.raise_for_status()
        data = response.json()
        raw_results = data.get("results", [])
        formatted = _rank_openalex_results(raw_results, query, sort=sort, limit=max_results)
        return json.dumps(
            {
                "engine": "openalex",
                "query": query,
                "count_returned": len(formatted),
                "filters": {
                    "from_year": from_year,
                    "to_year": to_year,
                    "open_access_only": open_access_only,
                    "sort": sort or "relevance",
                },
                "results": formatted,
            },
            ensure_ascii=False,
            indent=2,
        )


# ═══════════════════════════════════════════════════════════════
# 模块级辅助函数
# ═══════════════════════════════════════════════════════════════


def _extract_readable_text(html: str) -> str:
    """从 HTML 中提取干净的正文文本，自动识别正文区域。"""
    soup = BeautifulSoup(html, "html.parser")

    # 移除非正文标签
    for tag in soup(_STRIP_TAGS):
        tag.decompose()
    # 移除 HTML 注释
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # 尝试定位正文容器
    article = None
    for selector in _ARTICLE_SELECTORS:
        article = soup.select_one(selector)
        if article:
            break

    target = article or soup.body or soup

    # 按块级元素提取文本，保留结构
    blocks: list[str] = []
    for element in target.descendants:
        if isinstance(element, NavigableString) and not isinstance(element, Comment):
            text = element.strip()
            if text:
                parent = element.parent
                if isinstance(parent, Tag) and parent.name in {
                    "p", "h1", "h2", "h3", "h4", "h5", "h6",
                    "li", "td", "th", "blockquote", "figcaption",
                    "dt", "dd", "summary",
                }:
                    blocks.append(text)
                elif isinstance(parent, Tag) and parent.name == "pre":
                    blocks.append(text)
                else:
                    if blocks and blocks[-1] != text:
                        blocks.append(text)

    # 合并、去重连续空行
    text = "\n".join(blocks)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _jina_reader_fetch(url: str, limit: int = 12000) -> str:
    """用 Jina Reader (`r.jina.ai`) 抓取并直出 markdown，对 SPA / JS 渲染页效果远好于 BS4。"""
    jina_key = _get_jina_key()
    headers = {
        "Accept": "text/markdown",
        "X-Return-Format": "markdown",
        "User-Agent": "pooh-code/jina-reader",
    }
    if jina_key:
        headers["Authorization"] = f"Bearer {jina_key}"
    resp = httpx.get(_JINA_READER_URL + url, headers=headers, timeout=25.0, follow_redirects=True)
    resp.raise_for_status()
    text = (resp.text or "").strip()
    if not text:
        raise ValueError("jina reader returned empty body")
    return _truncate(text, limit)


def _bs4_fetch_and_extract(url: str, limit: int = 12000) -> str:
    """直接抓 HTML + BeautifulSoup 提取正文，作为 Jina Reader 的兜底。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    response = httpx.get(url, timeout=20.0, follow_redirects=True, headers=headers)
    response.raise_for_status()
    text = _extract_readable_text(response.text)
    return _truncate(text, limit)


def _fetch_and_extract(url: str, limit: int = 12000) -> str:
    """抓取网页并提取正文：优先 Jina Reader（markdown 输出，SPA 也能解析），失败回退到 BS4。"""
    if _get_jina_key():
        try:
            return _jina_reader_fetch(url, limit)
        except Exception as exc:
            logger.warning("jina reader failed for %s: %s; falling back to BS4", url, exc)
    return _bs4_fetch_and_extract(url, limit)


def _decode_openalex_abstract(inverted_index: dict[str, Any] | None) -> str:
    if not isinstance(inverted_index, dict) or not inverted_index:
        return ""
    pairs: list[tuple[int, str]] = []
    for token, positions in inverted_index.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            if isinstance(pos, int):
                pairs.append((pos, token))
    if not pairs:
        return ""
    pairs.sort(key=lambda item: item[0])
    return " ".join(token for _, token in pairs)


def _normalize_doi(doi: str | None) -> str:
    value = (doi or "").strip()
    if not value:
        return ""
    if value.startswith("https://doi.org/"):
        return value
    if value.lower().startswith("doi:"):
        value = value[4:].strip()
    return f"https://doi.org/{value}"


def _authors_string(authorships: Any, limit: int = 6) -> str:
    if not isinstance(authorships, list):
        return ""
    names: list[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        name = str(author.get("display_name", "")).strip()
        if name:
            names.append(name)
    if len(names) > limit:
        return ", ".join(names[:limit]) + f", 等 {len(names)} 位作者"
    return ", ".join(names)


def _authors_list(authorships: Any, limit: int = 20) -> list[str]:
    if not isinstance(authorships, list):
        return []
    names: list[str] = []
    for authorship in authorships:
        if not isinstance(authorship, dict):
            continue
        author = authorship.get("author") or {}
        name = str(author.get("display_name", "")).strip()
        if name:
            names.append(name)
        if len(names) >= limit:
            break
    return names


def _citation_short(authors: list[str], year: int | None) -> str:
    if not authors:
        return f"(匿名, {year or 'n.d.'})"
    first = authors[0]
    return f"({first} et al., {year or 'n.d.'})" if len(authors) > 1 else f"({first}, {year or 'n.d.'})"


def _citation_reference_text(
    *,
    authors: list[str],
    year: int | None,
    title: str,
    venue: str,
    doi_url: str,
    landing_page_url: str,
) -> str:
    author_text = ", ".join(authors) if authors else "匿名"
    parts = [f"{author_text}"]
    parts.append(f"({year or 'n.d.'}).")
    parts.append(title.strip() + ".")
    if venue:
        parts.append(venue.strip() + ".")
    if doi_url:
        parts.append(doi_url)
    elif landing_page_url:
        parts.append(landing_page_url)
    return " ".join(part for part in parts if part).strip()


def _format_openalex_work(item: dict[str, Any]) -> dict[str, Any]:
    primary_location = item.get("primary_location") or {}
    best_oa_location = item.get("best_oa_location") or {}
    primary_source = primary_location.get("source") or {}
    best_oa_source = best_oa_location.get("source") or {}
    open_access = item.get("open_access") or {}
    doi_url = _normalize_doi(item.get("doi"))
    abstract = _truncate(_decode_openalex_abstract(item.get("abstract_inverted_index")), 1500)
    landing_page_url = (
        best_oa_location.get("landing_page_url")
        or primary_location.get("landing_page_url")
        or doi_url
        or item.get("id", "")
    )
    pdf_url = best_oa_location.get("pdf_url") or primary_location.get("pdf_url") or ""
    venue = (
        best_oa_source.get("display_name")
        or primary_source.get("display_name")
        or ""
    )
    authors = _authors_list(item.get("authorships"))
    year = item.get("publication_year")
    citation_short = _citation_short(authors, year if isinstance(year, int) else None)
    reference_text = _citation_reference_text(
        authors=authors,
        year=year if isinstance(year, int) else None,
        title=str(item.get("display_name", "")),
        venue=venue,
        doi_url=doi_url,
        landing_page_url=landing_page_url,
    )
    return {
        "title": item.get("display_name", ""),
        "authors": _authors_string(item.get("authorships")),
        "authors_list": authors,
        "publication_year": year,
        "publication_date": item.get("publication_date", ""),
        "venue": venue,
        "type": item.get("type", ""),
        "cited_by_count": item.get("cited_by_count"),
        "doi": doi_url,
        "openalex_id": item.get("id", ""),
        "is_open_access": bool(open_access.get("is_oa")),
        "oa_status": open_access.get("oa_status", ""),
        "landing_page_url": landing_page_url,
        "pdf_url": pdf_url,
        "abstract": abstract,
        "inline_citation": citation_short,
        "reference_text": reference_text,
    }


def _tokenize_paper_query(query: str) -> list[str]:
    tokens = re.findall(r"[\w-]+", query.lower())
    filtered = [tok for tok in tokens if len(tok) >= 3 and tok not in _PAPER_STOPWORDS]
    return filtered or tokens[:8]


def _paper_relevance_score(item: dict[str, Any], query: str, tokens: list[str]) -> float:
    title = str(item.get("display_name", "")).lower()
    abstract = _decode_openalex_abstract(item.get("abstract_inverted_index")).lower()
    venue = str(((item.get("primary_location") or {}).get("source") or {}).get("display_name", "")).lower()
    searchable = " ".join(part for part in [title, abstract, venue] if part)

    score = 0.0
    query_lower = query.lower().strip()
    if query_lower and query_lower in title:
        score += 10.0
    elif query_lower and query_lower in searchable:
        score += 4.0

    phrases: list[str] = []
    for size in (3, 2):
        for idx in range(0, max(len(tokens) - size + 1, 0)):
            phrase = " ".join(tokens[idx : idx + size]).strip()
            if phrase:
                phrases.append(phrase)
    for phrase in phrases:
        if phrase in title:
            score += 4.0
        elif phrase in abstract:
            score += 2.0

    for token in tokens:
        if token in title:
            score += 3.0
        if token in abstract:
            score += 1.5
        if token in venue:
            score += 0.5
    return score


def _rank_openalex_results(
    raw_results: list[dict[str, Any]],
    query: str,
    *,
    sort: str,
    limit: int,
) -> list[dict[str, Any]]:
    current_year = datetime.now().year + 1
    tokens = _tokenize_paper_query(query)
    ranked: list[tuple[float, int, dict[str, Any]]] = []
    fallback: list[tuple[float, int, dict[str, Any]]] = []
    seen_keys: set[str] = set()

    for item in raw_results:
        year = item.get("publication_year")
        if isinstance(year, int) and year > current_year:
            continue
        item_type = str(item.get("type", "")).lower()
        formatted = _format_openalex_work(item)
        dedupe_key = (formatted.get("title") or formatted.get("doi") or formatted.get("openalex_id") or "").strip().lower()
        if dedupe_key and dedupe_key in seen_keys:
            continue
        if dedupe_key:
            seen_keys.add(dedupe_key)
        relevance = _paper_relevance_score(item, query, tokens)
        citation_bonus = min(float(item.get("cited_by_count") or 0), 5000.0) / 5000.0
        year_bonus = 0.0
        if isinstance(year, int):
            year_bonus = max(year - 2000, 0) / 100.0

        if sort == "cited_by_count":
            final_score = relevance * 3.0 + citation_bonus * 4.0 + year_bonus
        elif sort == "publication_year":
            final_score = relevance * 3.0 + year_bonus * 4.0 + citation_bonus
        else:
            final_score = relevance * 4.0 + citation_bonus + year_bonus

        bucket = ranked if item_type in _PAPER_RESULT_TYPES else fallback
        bucket.append((final_score, int(year or 0), formatted))

    ranked.sort(key=lambda row: (row[0], row[1]), reverse=True)
    fallback.sort(key=lambda row: (row[0], row[1]), reverse=True)
    merged = [row[2] for row in ranked]
    if len(merged) < limit:
        merged.extend(row[2] for row in fallback[: limit - len(merged)])
    return merged[:limit]


# ── 统一结果格式 ─────────────────────────────────────────────
# 每条结果结构：
# {
#   "title": str,
#   "url": str,
#   "content": str,        # 摘要 / snippet
#   "score": float | None, # 引擎返回的相关性分数（归一化到 0-1）
#   "source": str,         # 来源引擎：tavily / brave / duckduckgo
# }


# ── Tavily ─────────────────────────────────────────────────────


def _tavily_search_raw(
    query: str, max_results: int = 5, search_depth: str = "basic"
) -> list[dict[str, Any]]:
    payload = {
        "api_key": _get_tavily_key(),
        "query": query,
        "search_depth": search_depth,
        "max_results": max_results,
        "include_answer": True,
        "include_raw_content": False,
    }
    resp = httpx.post(_TAVILY_SEARCH_URL, json=payload, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    raw_results = data.get("results", [])
    formatted: list[dict[str, Any]] = []
    # Tavily 的 answer 作为一条置顶结果
    answer = data.get("answer")
    if answer:
        formatted.append({
            "title": "Tavily AI Answer",
            "url": "",
            "content": answer,
            "score": 1.0,
            "source": "tavily",
            "site": "",
            "language": "",
        })
    for item in raw_results:
        url = item.get("url", "")
        site = ""
        try:
            site = (urlparse(url).netloc or "").lower()
        except Exception:
            pass
        formatted.append({
            "title": item.get("title", ""),
            "url": url,
            "content": item.get("content", ""),
            "score": item.get("score"),
            "source": "tavily",
            "site": site,
            "language": "",
        })
    return formatted


# ── Brave ──────────────────────────────────────────────────────


def _strip_html(text: str) -> str:
    """剥离 HTML 标签（Brave description 里带 <strong> 高亮标签）。"""
    if not text:
        return ""
    # 去标签
    text = re.sub(r"<[^>]+>", "", text)
    # HTML 实体解码（最常见的几个）
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
        .replace("&nbsp;", " ")
    )
    return text.strip()


def _brave_search_raw(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": _get_brave_key(),
    }
    params = {
        "q": query,
        "count": min(max(max_results, 1), 20),
        "safesearch": "moderate",
        "extra_snippets": "true",  # 明确请求 extra_snippets
    }
    resp = httpx.get(_BRAVE_SEARCH_URL, params=params, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    web_results = (data.get("web") or {}).get("results", [])
    formatted: list[dict[str, Any]] = []
    for item in web_results:
        title = _strip_html(item.get("title", ""))
        description = _strip_html(item.get("description", ""))
        extra = item.get("extra_snippets") or []
        extra_clean = [_strip_html(s) for s in extra if s]
        # 把 description 和 extra_snippets 合并，用分隔符，方便 agent 阅读
        content_parts: list[str] = []
        if description:
            content_parts.append(description)
        if extra_clean:
            content_parts.append("— 更多片段 —")
            content_parts.extend(f"• {s}" for s in extra_clean)
        content = "\n".join(content_parts)

        # 站点信息（profile.long_name 通常是 host，如 docs.python.org）
        site = ((item.get("profile") or {}).get("long_name") or "").strip()
        language = (item.get("language") or "").strip()

        formatted.append({
            "title": title,
            "url": item.get("url", ""),
            "content": content,
            "score": None,  # Brave 不返回分数
            "source": "brave",
            "site": site,
            "language": language,
        })
    return formatted


# ── Bocha（博查，中文友好）────────────────────────────────────


def _bocha_search_raw(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    """博查 web-search：对中文站（知乎/微信公众号/CSDN/小红书等）召回明显强于 Tavily/Brave。"""
    headers = {
        "Authorization": f"Bearer {_get_bocha_key()}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "summary": True,
        "count": min(max(max_results, 1), 20),
        "freshness": "noLimit",
    }
    resp = httpx.post(_BOCHA_SEARCH_URL, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    pages = (((data.get("data") or {}).get("webPages") or {}).get("value")) or []
    formatted: list[dict[str, Any]] = []
    for item in pages:
        url = item.get("url", "") or ""
        try:
            site = (urlparse(url).netloc or "").lower()
        except Exception:
            site = item.get("siteName", "") or ""
        snippet = item.get("summary") or item.get("snippet") or ""
        formatted.append({
            "title": _strip_html(item.get("name", "")),
            "url": url,
            "content": _strip_html(snippet),
            "score": None,
            "source": "bocha",
            "site": site,
            "language": "zh" if _is_chinese_query(snippet or item.get("name", "")) else "",
        })
    return formatted


# ── Exa（神经/语义检索）───────────────────────────────────────


def _exa_search_raw(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    """Exa 语义检索：擅长"找类似文章/技术博客/研究内容"。"""
    headers = {
        "x-api-key": _get_exa_key(),
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "type": "auto",  # auto 让 Exa 自己选 keyword/neural
        "numResults": min(max(max_results, 1), 15),
        "contents": {"text": {"maxCharacters": 800}},
    }
    resp = httpx.post(_EXA_SEARCH_URL, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("results", []) or []
    formatted: list[dict[str, Any]] = []
    for item in raw:
        url = item.get("url", "") or ""
        try:
            site = (urlparse(url).netloc or "").lower()
        except Exception:
            site = ""
        text_content = item.get("text") or item.get("snippet") or ""
        formatted.append({
            "title": item.get("title", ""),
            "url": url,
            "content": text_content,
            "score": item.get("score"),
            "source": "exa",
            "site": site,
            "language": "",
        })
    return formatted


# ── Search1API（Google/Bing 元搜索聚合，兜底加宽召回）────────────


def _search1api_search_raw(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {_get_search1api_key()}",
        "Content-Type": "application/json",
    }
    payload = {
        "query": query,
        "search_service": "google",
        "max_results": min(max(max_results, 1), 20),
    }
    resp = httpx.post(_SEARCH1API_URL, json=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("results", []) or []
    formatted: list[dict[str, Any]] = []
    for item in raw:
        url = item.get("link") or item.get("url", "")
        try:
            site = (urlparse(url).netloc or "").lower()
        except Exception:
            site = ""
        formatted.append({
            "title": item.get("title", ""),
            "url": url,
            "content": item.get("snippet") or item.get("content", ""),
            "score": None,
            "source": "search1api",
            "site": site,
            "language": "",
        })
    return formatted


# ── DuckDuckGo (fallback) ─────────────────────────────────────


def _ddg_search_raw(query: str, max_results: int = 8) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    with DDGS() as ddgs:
        for item in ddgs.text(query, max_results=max_results):
            url = item.get("href", "")
            site = ""
            try:
                site = (urlparse(url).netloc or "").lower()
            except Exception:
                pass
            results.append({
                "title": item.get("title", ""),
                "url": url,
                "content": item.get("body", ""),
                "score": None,
                "source": "duckduckgo",
                "site": site,
                "language": "",
            })
    return results


# ── 多引擎调度与合并 ───────────────────────────────────────────


def _normalize_url(url: str) -> str:
    """归一化 URL 用于去重：小写 host、去 fragment、去末尾斜杠。"""
    if not url:
        return ""
    try:
        p = urlparse(url)
        host = (p.netloc or "").lower()
        path = (p.path or "").rstrip("/")
        return f"{p.scheme}://{host}{path}?{p.query}" if p.query else f"{p.scheme}://{host}{path}"
    except Exception:
        return url


def _merge_results(
    result_lists: list[list[dict[str, Any]]], max_results: int
) -> list[dict[str, Any]]:
    """多引擎结果合并：按 URL 去重，interleave 交叉，保留多源命中的加权。"""
    seen: dict[str, dict[str, Any]] = {}
    # 按轮次交错合并：rank 越靠前的越优先
    max_len = max((len(lst) for lst in result_lists), default=0)
    for i in range(max_len):
        for lst in result_lists:
            if i >= len(lst):
                continue
            item = lst[i]
            key = _normalize_url(item.get("url", "")) or item.get("title", "")
            if not key:
                continue
            if key in seen:
                # 多引擎命中 → 记录所有来源，用于提升可信度
                existing = seen[key]
                sources = set(existing.get("source", "").split("+"))
                sources.add(item.get("source", ""))
                existing["source"] = "+".join(sorted(s for s in sources if s))
                # 如果现有 content 较短，用新的更详细的替换
                if len(item.get("content", "")) > len(existing.get("content", "")):
                    existing["content"] = item["content"]
            else:
                seen[key] = dict(item)
    merged = list(seen.values())
    # 多源命中的排前面
    merged.sort(key=lambda x: (-x.get("source", "").count("+"), 0))
    return merged[:max_results]


_ENGINE_RUNNERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "tavily": lambda q, n, depth="basic": _tavily_search_raw(q, n, depth),
    "brave": lambda q, n, **_: _brave_search_raw(q, n),
    "bocha": lambda q, n, **_: _bocha_search_raw(q, n),
    "exa": lambda q, n, **_: _exa_search_raw(q, n),
    "search1api": lambda q, n, **_: _search1api_search_raw(q, n),
    "duckduckgo": lambda q, n, **_: _ddg_search_raw(q, n),
}


def _engine_available(name: str) -> bool:
    if name == "tavily":
        return bool(_get_tavily_key())
    if name == "brave":
        return bool(_get_brave_key())
    if name == "bocha":
        return bool(_get_bocha_key())
    if name == "exa":
        return bool(_get_exa_key())
    if name == "search1api":
        return bool(_get_search1api_key())
    if name == "duckduckgo":
        return True
    return False


def _route_engines(query: str) -> list[str]:
    """auto 模式下根据 query 特征挑 2–3 个最契合的引擎，避免无脑全跑。"""
    if _is_neural_query(query):
        # "找类似/相关研究" → Exa 神经 + Tavily 摘要
        plan = ["exa", "tavily", "brave"]
    elif _is_chinese_query(query):
        # 中文 query → 博查抓中文站 + Tavily 兜全局
        plan = ["bocha", "tavily", "brave"]
    elif _is_news_query(query):
        # 时效性 → Tavily(answer 含时间) + Brave + Bocha
        plan = ["tavily", "brave", "bocha"]
    else:
        # 默认英文/通用 → Tavily + Brave + Exa
        plan = ["tavily", "brave", "exa"]

    available = [name for name in plan if _engine_available(name)]
    if not available:
        # 所有首选都没配 → 退到任何配了 key 的引擎
        for fallback in ("tavily", "brave", "bocha", "exa", "search1api"):
            if _engine_available(fallback):
                available.append(fallback)
        if not available:
            available.append("duckduckgo")
    return available


def _search_dispatch(
    query: str,
    max_results: int,
    engine: str = "auto",
    search_depth: str = "basic",
) -> list[dict[str, Any]]:
    """根据 engine 参数调度搜索；auto 模式按 query 特征智能选引擎并行合并。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    # 单引擎模式
    if engine in _ENGINE_RUNNERS and engine != "duckduckgo":
        if not _engine_available(engine):
            return []
        runner = _ENGINE_RUNNERS[engine]
        try:
            return runner(query, max_results, depth=search_depth)
        except Exception as exc:
            logger.warning("%s search failed: %s", engine, exc)
            return []
    if engine == "duckduckgo":
        return _ddg_search_raw(query, max_results)

    # auto：智能路由
    chosen = _route_engines(query)
    if chosen == ["duckduckgo"]:
        return _ddg_search_raw(query, max_results)

    per_engine = max(max_results, 5)
    tasks: dict[Any, str] = {}
    with ThreadPoolExecutor(max_workers=max(len(chosen), 1)) as pool:
        for name in chosen:
            runner = _ENGINE_RUNNERS[name]
            tasks[pool.submit(runner, query, per_engine, depth=search_depth)] = name

        result_lists: list[list[dict[str, Any]]] = []
        for future in as_completed(tasks):
            name = tasks[future]
            try:
                result_lists.append(future.result())
            except Exception as exc:
                logger.warning("%s search failed: %s", name, exc)

    if not result_lists:
        logger.warning("All routed engines failed; falling back to DuckDuckGo")
        return _ddg_search_raw(query, max_results)

    return _merge_results(result_lists, max_results)


# ── Jina DeepSearch（深度研究）────────────────────────────────


def _jina_deepsearch(query: str, reasoning_effort: str = "medium") -> dict[str, Any]:
    """Jina DeepSearch：迭代式 search → read → reason，直接产出带引用的研究答案。"""
    jina_key = _get_jina_key()
    if not jina_key:
        raise RuntimeError("JINA_API_KEY not configured")
    headers = {
        "Authorization": f"Bearer {jina_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "model": "jina-deepsearch-v1",
        "messages": [{"role": "user", "content": query}],
        "stream": False,
        "reasoning_effort": reasoning_effort,
    }
    resp = httpx.post(_JINA_DEEPSEARCH_URL, json=payload, headers=headers, timeout=180.0)
    resp.raise_for_status()
    data = resp.json()
    choices = data.get("choices") or []
    answer = ""
    if choices:
        msg = choices[0].get("message") or {}
        answer = msg.get("content") or ""
    visited_urls = data.get("visitedURLs") or []
    return {
        "answer": answer,
        "visited_urls": visited_urls,
        "usage": data.get("usage", {}),
    }
