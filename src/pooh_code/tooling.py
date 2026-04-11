from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import logging
import re

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from duckduckgo_search import DDGS

from .models import ToolSpec
from .paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

MAX_TOOL_OUTPUT = 40000


def _get_tavily_key() -> str:
    return os.getenv("TAVILY_API_KEY", "")


def _get_brave_key() -> str:
    return os.getenv("BRAVE_API_KEY", "")


_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# 需要移除的非正文标签
_STRIP_TAGS = {"script", "style", "noscript", "nav", "footer", "header", "aside", "iframe", "svg"}
# 常见正文容器的 CSS 选择器（按优先级排列）
_ARTICLE_SELECTORS = ["article", "main", "[role='main']", ".post-content", ".article-content", ".entry-content", ".content"]


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
                description=(
                    "Fetch a web page and extract its main content as clean readable text. "
                    "Automatically strips navigation, ads, and boilerplate. "
                    "Use this when you already have a specific URL to read."
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
                    "Search the web using multiple engines in parallel (Tavily + Brave by default) "
                    "and merge deduplicated results. Falls back to DuckDuckGo if all configured "
                    "engines fail. Returns titles, URLs, and snippets with source engine labels."
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
                            "enum": ["auto", "tavily", "brave", "duckduckgo"],
                            "description": "auto: multi-engine merge (default); or a single engine.",
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
                name="web_search_and_read",
                description=(
                    "Search the web and automatically fetch the full content of top results. "
                    "More thorough than web_search alone — use this when you need detailed "
                    "information, not just snippets. Equivalent to search + fetch for each result."
                ),
                input_schema={
                    "type": "object",
                    "required": ["query"],
                    "properties": {
                        "query": {"type": "string", "description": "Search query string."},
                        "max_results": {
                            "type": "integer",
                            "description": "Number of pages to fetch (default 3, max 5).",
                        },
                    },
                },
            ),
            self._web_search_and_read,
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
        return json.dumps(results, ensure_ascii=False, indent=2)

    # ── web: search + read ──────────────────────────────────────

    def _web_search_and_read(self, query: str, max_results: int = 3) -> str:
        max_results = min(max(max_results, 1), 5)
        search_results = _search_dispatch(query, max_results, "auto", "advanced")

        # 逐个抓取正文
        output_parts = []
        for i, item in enumerate(search_results):
            url = item.get("url") or item.get("href", "")
            title = item.get("title", "")
            snippet = item.get("content") or item.get("body", "")
            section = f"## [{i+1}] {title}\nURL: {url}\n"
            if snippet:
                section += f"摘要: {snippet}\n"
            # 尝试抓取完整正文
            try:
                full_text = _fetch_and_extract(url, limit=6000)
                section += f"\n--- 正文 ---\n{full_text}\n"
            except Exception as exc:
                section += f"\n(抓取失败: {exc})\n"
            output_parts.append(section)

        return _truncate("\n".join(output_parts))


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


def _fetch_and_extract(url: str, limit: int = 12000) -> str:
    """抓取网页并提取正文。"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    response = httpx.get(url, timeout=20.0, follow_redirects=True, headers=headers)
    response.raise_for_status()
    text = _extract_readable_text(response.text)
    return _truncate(text, limit)


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


def _search_dispatch(
    query: str,
    max_results: int,
    engine: str = "auto",
    search_depth: str = "basic",
) -> list[dict[str, Any]]:
    """根据 engine 参数调度搜索；auto 模式并行多引擎合并。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    tavily_key = _get_tavily_key()
    brave_key = _get_brave_key()

    # 单引擎模式
    if engine == "tavily":
        return _tavily_search_raw(query, max_results, search_depth) if tavily_key else []
    if engine == "brave":
        return _brave_search_raw(query, max_results) if brave_key else []
    if engine == "duckduckgo":
        return _ddg_search_raw(query, max_results)

    # auto：并行多引擎
    tasks: dict[Any, str] = {}
    # 每个引擎各自取 max_results 条，合并后再截断
    per_engine = max(max_results, 5)
    with ThreadPoolExecutor(max_workers=3) as pool:
        if tavily_key:
            tasks[pool.submit(_tavily_search_raw, query, per_engine, search_depth)] = "tavily"
        if brave_key:
            tasks[pool.submit(_brave_search_raw, query, per_engine)] = "brave"
        if not tasks:
            # 两家都没 key → 用 DDG 兜底
            return _ddg_search_raw(query, max_results)

        result_lists: list[list[dict[str, Any]]] = []
        for future in as_completed(tasks):
            name = tasks[future]
            try:
                result_lists.append(future.result())
            except Exception as exc:
                logger.warning("%s search failed: %s", name, exc)

    if not result_lists:
        # 所有配置的引擎都挂了 → DDG 兜底
        logger.warning("All configured engines failed; falling back to DuckDuckGo")
        return _ddg_search_raw(query, max_results)

    return _merge_results(result_lists, max_results)
