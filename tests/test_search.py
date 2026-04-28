"""搜索栈端到端测试脚本。

运行：
    uv run python tests/test_search.py

分四个 section：
    1. 智能路由单测（不打外网，验证 _route_engines / _is_*_query 逻辑）
    2. 各引擎实调冒烟测试（真实 API，需要对应 key；任何一家失败不影响其他）
    3. 工具注册验证（确认 web_fetch / web_search / deep_research / paper_search 都注册，
       web_search_and_read 已被移除）
    4. 用户给的具体混合 query 实测路由 + 跑一次 web_search 看 source 分布
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

# 把项目根加进 sys.path，方便直接 `python tests/test_search.py`
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.pooh_code.config import load_settings  # noqa: E402

# 启动时把 settings.json 里的 key 同步到环境变量
load_settings()

from src.pooh_code.tooling import (  # noqa: E402
    ToolRegistry,
    _bocha_search_raw,
    _brave_search_raw,
    _ddg_search_raw,
)


def _section(title: str) -> None:
    print("\n" + "═" * 70)
    print(f"  {title}")
    print("═" * 70)


def _ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def _fail(msg: str) -> None:
    print(f"  ❌ {msg}")


def _warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")


# ─── Section 1: 路由单测 ────────────────────────────────────────────

def test_routing() -> None:
    _section("1. 路由单测（auto 默认覆盖中英文双向，只有 neural 触发才换 plan）")
    from src.pooh_code.tooling import _is_neural_query, _route_engines

    DEFAULT = ["tavily", "brave", "bocha"]
    NEURAL = ["exa", "tavily", "brave"]

    cases: list[tuple[str, list[str], str]] = [
        # 默认所有 query 都走 Tavily+Brave+Bocha 三家
        ("比亚迪秦L的电池热管理方案", DEFAULT, "纯中文 — 默认三家"),
        ("rust async runtime comparison", DEFAULT, "纯英文 — 默认三家"),
        ("OpenAI 2026 latest news", DEFAULT, "时效 — 默认三家"),
        (
            "你再去查一下ontotext的railway asset management solution，有可量化数据的产品效益吗",
            DEFAULT,
            "用户案例（中文壳+英文实体）— 默认三家覆盖中英文",
        ),
        ("比亚迪海外销量分析", DEFAULT, "国内厂商海外信息 — 默认三家避免漏一手英文源"),
        ("NVIDIA H100 中国行情价", DEFAULT, "海外厂商国内信息 — 默认三家覆盖中文社区"),
        # 只有 neural 触发会切到 Exa
        ("find papers similar to RAG retrieval reranking", NEURAL, "neural 触发 — 切 Exa"),
        ("帮我找类似的博客 about agent memory", NEURAL, "中文 neural 触发"),
    ]

    for q, expected, note in cases:
        neural = _is_neural_query(q)
        plan = _route_engines(q)
        print(f"\n  [{note}] query: {q[:60]}{'…' if len(q) > 60 else ''}")
        print(f"    neural={neural}  plan={plan}")
        if plan == expected:
            _ok(f"路由匹配预期 {expected}")
        else:
            _fail(f"路由不匹配，期望 {expected}，实际 {plan}")


# ─── Section 2: 各引擎实调冒烟 ──────────────────────────────────────

def test_engines_smoke() -> None:
    _section("2. 各引擎实调冒烟（真实 API，每家发一条 query 验证 key 与连通性）")
    import os
    from src.pooh_code.tooling import (
        _exa_search_raw, _jina_deepsearch, _jina_reader_fetch,
        _search1api_search_raw, _tavily_search_raw,
    )

    Q_EN = "python httpx async client"
    Q_ZH = "比亚迪海豹电池"

    plans = [
        ("Tavily", "TAVILY_API_KEY", lambda: _tavily_search_raw(Q_EN, max_results=3)),
        ("Brave", "BRAVE_API_KEY", lambda: _brave_search_raw(Q_EN, max_results=3)),
        ("Bocha", "BOCHA_API_KEY", lambda: _bocha_search_raw(Q_ZH, max_results=3)),
        ("Exa", "EXA_API_KEY", lambda: _exa_search_raw(Q_EN, max_results=3)),
        ("Search1API", "SEARCH1API_KEY", lambda: _search1api_search_raw(Q_EN, max_results=3)),
        ("DuckDuckGo (no key)", None, lambda: _ddg_search_raw(Q_EN, max_results=3)),
    ]

    for name, env_key, runner in plans:
        if env_key is not None and not os.getenv(env_key, ""):
            _warn(f"{name} 未配置 {env_key}，跳过")
            continue
        try:
            results = runner()
        except Exception as exc:
            _fail(f"{name} 调用失败：{exc}")
            continue
        if not results:
            _fail(f"{name} 返回空结果")
            continue
        first = results[0]
        title = (first.get("title") or "")[:50]
        url = first.get("url", "")
        _ok(f"{name}: count={len(results)}  source={first.get('source')}  "
            f"top='{title}'  url={url[:60]}")

    # Jina Reader 单独测一下抓取
    print()
    if os.getenv("JINA_API_KEY"):
        try:
            text = _jina_reader_fetch("https://example.com", limit=400)
            if "Example Domain" in text:
                _ok(f"Jina Reader: 抓取 example.com 正常，长度={len(text)}")
            else:
                _warn(f"Jina Reader: 抓回内容但没找到关键字，预览={text[:120]!r}")
        except Exception as exc:
            _fail(f"Jina Reader 调用失败：{exc}")
    else:
        _warn("Jina Reader 未配置 JINA_API_KEY")

    # Jina DeepSearch（耗时较长，单独 try，超时也算 PASS-with-warn）
    print()
    if os.getenv("JINA_API_KEY"):
        try:
            print("  ⏳ Jina DeepSearch 调用中（~30-90s，迭代搜索阶段会慢）...")
            ds = _jina_deepsearch("What is RAG retrieval augmented generation?", reasoning_effort="low")
            ans = (ds.get("answer") or "").strip()
            urls = ds.get("visited_urls") or []
            if ans:
                _ok(f"Jina DeepSearch: answer 长度={len(ans)}  visited_urls={len(urls)} 个")
            else:
                _warn(f"Jina DeepSearch 返回空 answer，usage={ds.get('usage')}")
        except Exception as exc:
            _fail(f"Jina DeepSearch 调用失败：{exc}")
    else:
        _warn("Jina DeepSearch 未配置 JINA_API_KEY")


# ─── Section 3: 工具注册验证 ────────────────────────────────────────

def test_tool_registry() -> None:
    _section("3. 工具注册验证（确认工具列表与描述）")
    registry = ToolRegistry(readonly=False)
    spec_map = {spec["name"]: spec for spec in registry.specs()}
    names = sorted(spec_map.keys())
    print(f"  已注册工具: {names}")

    expected_present = ["web_fetch", "web_search", "deep_research", "paper_search"]
    expected_absent = ["web_search_and_read"]

    for name in expected_present:
        if name in spec_map:
            _ok(f"{name} 已注册")
        else:
            _fail(f"{name} 未注册")

    for name in expected_absent:
        if name in spec_map:
            _fail(f"{name} 仍存在（应已被移除）")
        else:
            _ok(f"{name} 已移除")

    # 关键词审计：deep_research 描述里是否突出"开放式研究 / 带引用"特征，
    # 让 agent 在不该用 web_search 的场景里识别出来
    if "deep_research" in spec_map:
        desc = spec_map["deep_research"]["description"].lower()
        signals = ["iterative", "deepsearch", "cited", "research"]
        hit = [s for s in signals if s in desc]
        if len(hit) >= 2:
            _ok(f"deep_research 描述包含触发信号: {hit}")
        else:
            _warn(f"deep_research 描述触发信号偏弱（仅 {hit}），agent 可能不会主动调用")

    if "web_search" in spec_map:
        desc = spec_map["web_search"]["description"].lower()
        signals = ["chinese", "bocha", "exa", "neural", "news"]
        hit = [s for s in signals if s in desc]
        if len(hit) >= 3:
            _ok(f"web_search 描述包含路由提示: {hit}")
        else:
            _warn(f"web_search 描述里路由提示偏少: {hit}")


# ─── Section 4: 用户案例实测 ────────────────────────────────────────

def test_user_case() -> None:
    _section("4. 实战 query：默认三家并跑能否覆盖跨境信息")
    from src.pooh_code.tooling import _route_engines, _search_dispatch

    cases = [
        "你再去查一下ontotext的railway asset management solution，有可量化数据的产品效益吗",
        "比亚迪海外销量 2025 分析",
    ]
    for q in cases:
        print(f"\n  query: {q}")
        plan = _route_engines(q)
        print(f"  路由: {plan}")
        print("  → 真实跑一次 _search_dispatch (auto)...")
        try:
            results = _search_dispatch(q, max_results=6, engine="auto")
            sources = sorted({r.get("source", "") for r in results if r.get("source")})
            print(f"    返回 {len(results)} 条，sources={sources}")
            # 用 host 分类看跨境覆盖情况
            zh_hosts = sum(
                1 for r in results
                if any(t in (r.get("url") or "") for t in [".cn", "zhihu", "csdn", "sohu", "weixin", "163.com", "yiche", "book118"])
            )
            print(f"    国内站 {zh_hosts} / 海外站 {len(results) - zh_hosts}")
            for i, r in enumerate(results[:5], 1):
                print(f"    [{i}] ({r.get('source')}) {r.get('title','')[:60]}")
                print(f"        {r.get('url','')}")
        except Exception as exc:
            _fail(f"_search_dispatch 失败：{exc}")
            traceback.print_exc()

    # 实跑一次，看 source 分布
    print("\n  → 真实跑一次 _search_dispatch (auto)...")
    try:
        results = _search_dispatch(q, max_results=6, engine="auto")
        sources = sorted({r.get("source", "") for r in results if r.get("source")})
        print(f"    返回 {len(results)} 条，sources={sources}")
        for i, r in enumerate(results[:5], 1):
            print(f"    [{i}] ({r.get('source')}) {r.get('title','')[:60]}")
            print(f"        {r.get('url','')}")
    except Exception as exc:
        _fail(f"_search_dispatch 失败：{exc}")
        traceback.print_exc()


# ─── 主入口 ────────────────────────────────────────────────────────

def main() -> None:
    print("\n" + "█" * 70)
    print("  Pooh-code 搜索栈测试")
    print("█" * 70)

    sections = [
        ("路由单测", test_routing),
        ("引擎冒烟", test_engines_smoke),
        ("工具注册", test_tool_registry),
        ("用户案例", test_user_case),
    ]
    for name, fn in sections:
        try:
            fn()
        except Exception as exc:
            _fail(f"section [{name}] 执行抛异常：{exc}")
            traceback.print_exc()

    print("\n" + "█" * 70)
    print("  测试完成")
    print("█" * 70 + "\n")


if __name__ == "__main__":
    main()
