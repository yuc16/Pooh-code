#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SERIES_URL = "https://www.autohome.com.cn/{series_id}"
PARAM_URL = "https://www.autohome.com.cn/web-main/car/param/getParamConf"
QP_FULL_URL = "https://sou.autohome.com.cn/afu_search_proxy_api/qp_full"
SEARCH_URL = "https://sou.api.autohome.com.cn/v1/search"
NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.S,
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
META_RE = re.compile(
    r'<meta[^>]+name=["\'](?P<name>description|keywords)["\'][^>]+content=["\'](?P<content>.*?)["\']',
    re.I | re.S,
)
USER_AGENT = "Mozilla/5.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "按 agent 显式给出的关键词执行汽车之家站内搜索，并对命中的车系补抓车系页和参数页。"
        )
    )
    parser.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        default=[],
        help="可重复传入；每个关键词/短语由 agent 基于专利内容自行决定",
    )
    parser.add_argument(
        "--series-id",
        dest="series_ids",
        action="append",
        type=int,
        default=[],
        help="可选，显式指定要补抓的汽车之家车系 ID；可重复传入",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="每个关键词最多保留多少条站内搜索结果，默认 10",
    )
    parser.add_argument(
        "--max-series",
        type=int,
        default=5,
        help="最多补抓多少个车系，默认 5",
    )
    parser.add_argument(
        "--cityid",
        default="110100",
        help="汽车之家搜索接口使用的城市 ID，默认 110100",
    )
    parser.add_argument("--output", help="输出 JSON 路径；不传则打印到标准输出")
    parser.add_argument("--patent-json", help="可选，附带专利 JSON 作为上下文")
    parser.add_argument("--topic-text", help="可选，附带主题文本作为上下文")
    parser.add_argument(
        "--include-raw",
        action="store_true",
        help="调试模式：附带 qp_full、搜索原始返回、参数原始分组等",
    )
    return parser.parse_args()


def fetch_text(url: str, params: dict[str, Any] | None = None, referer: str | None = None) -> str:
    full_url = f"{url}?{urlencode(params, doseq=True)}" if params else url
    req = Request(
        full_url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": referer or "https://www.autohome.com.cn/",
        },
    )
    with urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def fetch_json(url: str, params: dict[str, Any] | None = None, referer: str | None = None) -> dict[str, Any]:
    return json.loads(fetch_text(url, params=params, referer=referer))


def compact_text(value: Any) -> str:
    text = html.unescape(HTML_TAG_RE.sub("", str(value or "")))
    return re.sub(r"\s+", " ", text).strip()


def html_fragment_to_text(value: Any) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</?(p|div|li|ul|ol|section|article|h1|h2|h3|h4|h5|h6)[^>]*>", "\n", text)
    text = html.unescape(HTML_TAG_RE.sub("", text))
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return text.strip()


def first_nonempty(*values: Any) -> str:
    for value in values:
        text = compact_text(value)
        if text:
            return text
    return ""


def normalize_title(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("TIZH", "title", "TIEN", "TIJA"):
            text = value.get(key)
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def load_patent_context(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    claims = data.get("claims_zh") or []
    if not isinstance(claims, list):
        claims = []
    return {
        "patent_no": data.get("patent_no") or data.get("requested_pnm") or "",
        "title": normalize_title(data.get("title")),
        "claims_zh": [str(item).strip() for item in claims if str(item).strip()],
    }


def extract_page_metadata(html_text: str) -> dict[str, str]:
    title_match = re.search(r"<title>(.*?)</title>", html_text, re.I | re.S)
    metadata = {"title": "", "description": "", "keywords": ""}
    if title_match:
        metadata["title"] = compact_text(title_match.group(1))
    for match in META_RE.finditer(html_text):
        metadata[match.group("name").lower()] = compact_text(match.group("content"))
    return metadata


def extract_next_data(html_text: str) -> dict[str, Any]:
    match = NEXT_DATA_RE.search(html_text)
    if not match:
        raise SystemExit("未找到 __NEXT_DATA__。")
    return json.loads(html.unescape(match.group(1)))


def find_key(node: Any, key: str) -> Any:
    if isinstance(node, dict):
        if key in node:
            return node[key]
        for value in node.values():
            found = find_key(value, key)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_key(item, key)
            if found is not None:
                return found
    return None


def build_title_meta(title_list: list[dict[str, Any]]) -> dict[int, dict[str, str]]:
    title_meta: dict[int, dict[str, str]] = {}
    for group in title_list:
        itemtype = str(group.get("itemtype") or "").strip()
        groupname = str(group.get("groupname") or "").strip()
        for item in group.get("items", []):
            title_id = item.get("titleid")
            name = item.get("itemname")
            if isinstance(title_id, int) and name:
                title_meta[title_id] = {
                    "field": str(name),
                    "itemtype": itemtype,
                    "groupname": groupname,
                    "baikeurl": str(item.get("baikeurl") or "").strip(),
                }
    return title_meta


def normalize_value(item: dict[str, Any]) -> str:
    value = str(item.get("itemname") or "").strip()
    if value and value != "-":
        return value
    parts: list[str] = []
    for sub in item.get("sublist") or []:
        name = str(sub.get("name") or "").strip()
        sub_value = str(sub.get("value") or "").strip()
        if name and sub_value and sub_value not in {"●", "○"}:
            parts.append(f"{name}:{sub_value}")
        elif name:
            parts.append(name)
        elif sub_value:
            parts.append(sub_value)
    return "；".join(parts).strip()


def build_param_groups(
    param_json: dict[str, Any],
    target_spec_id: int,
) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    result = param_json.get("result") or {}
    title_meta = build_title_meta(result.get("titlelist") or [])
    datalist = result.get("datalist") or []
    spec = next(
        (item for item in datalist if item.get("specid") == target_spec_id),
        datalist[0] if datalist else {},
    )

    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    all_param_fields: dict[str, str] = {}
    searchable_lines: list[str] = []

    for item in spec.get("paramconflist") or []:
        title_id = item.get("titleid")
        meta = title_meta.get(title_id)
        if not meta:
            continue
        value = normalize_value(item)
        if not value:
            continue
        field = meta["field"]
        all_param_fields[field] = value
        subitems = []
        for sub in item.get("sublist") or []:
            sub_name = str(sub.get("name") or "").strip()
            sub_value = str(sub.get("value") or "").strip()
            if sub_name or sub_value:
                subitems.append({"name": sub_name, "value": sub_value})

        entry = {
            "field": field,
            "value": value,
            "title_id": title_id,
            "itemtype": meta["itemtype"],
            "groupname": meta["groupname"],
            "baikeurl": meta["baikeurl"],
            "subitems": subitems,
        }
        grouped.setdefault((meta["itemtype"], meta["groupname"]), []).append(entry)
        searchable_lines.append(f"{meta['groupname']} / {meta['itemtype']} / {field}: {value}")

    param_groups = []
    for (itemtype, groupname), entries in grouped.items():
        param_groups.append(
            {
                "itemtype": itemtype,
                "groupname": groupname,
                "entries": entries,
            }
        )
    return param_groups, all_param_fields, searchable_lines


def parse_merge_jump(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


def to_int_list(value: Any) -> list[int]:
    result: list[int] = []
    if isinstance(value, list):
        for item in value:
            result.extend(to_int_list(item))
        return result
    if isinstance(value, int):
        return [value]
    text = str(value or "").strip()
    if not text:
        return []
    for part in re.split(r"[,\s]+", text):
        if part.isdigit():
            result.append(int(part))
    return result


def to_text_list(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, list):
        for item in value:
            result.extend(to_text_list(item))
        return result
    text = compact_text(value)
    if not text:
        return []
    for part in re.split(r"[，,、/|]+", text):
        part = part.strip()
        if part and part not in result:
            result.append(part)
    return result


def build_search_terms(keywords: list[str]) -> list[str]:
    expanded_terms: list[str] = []
    for keyword in keywords:
        normalized = keyword.strip()
        if not normalized:
            continue
        if normalized not in expanded_terms:
            expanded_terms.append(normalized)
        for part in re.split(r"\s+", normalized):
            part = part.strip()
            if len(part) >= 2 and part not in expanded_terms:
                expanded_terms.append(part)
    return expanded_terms


def truncate_text(text: str, limit: int = 1200) -> str:
    normalized = compact_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 1].rstrip() + "…"


def first_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def split_text_blocks(*parts: Any) -> list[str]:
    blocks: list[str] = []
    for part in parts:
        text = html_fragment_to_text(part)
        if not text:
            continue
        for block in re.split(r"\n{2,}|\n", text):
            normalized = compact_text(block)
            if normalized:
                blocks.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for block in blocks:
        if block not in seen:
            seen.add(block)
            deduped.append(block)
    return deduped


def extract_keyword_snippets(*parts: Any, keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
    blocks = split_text_blocks(*parts)
    if not blocks:
        return []

    snippets: list[dict[str, Any]] = []
    seen_blocks: set[str] = set()
    search_terms = build_search_terms(keywords)

    scored_blocks: list[tuple[int, int, str, list[str]]] = []
    for index, block in enumerate(blocks):
        matched_terms = [term for term in search_terms if term and term in block]
        if not matched_terms:
            continue
        unique_terms = []
        for term in matched_terms:
            if term not in unique_terms:
                unique_terms.append(term)
        score = sum(len(term) for term in unique_terms)
        scored_blocks.append((score, -index, block, unique_terms))

    for _, _, block, matched_terms in sorted(scored_blocks, reverse=True):
        if block in seen_blocks:
            continue
        seen_blocks.add(block)
        snippets.append(
            {
                "keywords": matched_terms,
                "snippet": truncate_text(block, 220),
            }
        )
        if len(snippets) >= limit:
            break
    return snippets


def classify_search_item(item: dict[str, Any], source_box: dict[str, Any] | None = None) -> str:
    info = item.get("iteminfo") or {}
    item_type = str(item.get("type") or "")
    biz_type = int(info.get("biz_type") or 0)
    if source_box and "新闻资讯" in str(source_box.get("box_name") or ""):
        if biz_type == 14:
            return "文章视频"
        if biz_type == 13:
            return "短内容"
        return "文章"
    if source_box and "排行榜" in str(source_box.get("box_name") or ""):
        return "榜单"
    if item_type == "box":
        return "信息盒"
    if biz_type == 14:
        return "文章视频"
    if biz_type == 13:
        return "短内容"
    if biz_type == 12:
        return "文章"
    return "搜索结果"


def flatten_search_items(items: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any] | None]]:
    flattened: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
    for item in items:
        info = item.get("iteminfo") or {}
        box_data = info.get("data") if isinstance(info.get("data"), dict) else {}
        nested = box_data.get("itemlist") if isinstance(box_data, dict) else None
        if isinstance(nested, list) and nested:
            source_box = {
                "box_type": info.get("type") or "",
                "box_name": info.get("name") or "",
                "box_id": info.get("id") or "",
            }
            for child in nested:
                flattened.append((child, source_box))
        else:
            flattened.append((item, None))
    return flattened


def normalize_search_item(item: dict[str, Any], source_box: dict[str, Any] | None = None) -> dict[str, Any]:
    info = item.get("iteminfo") or {}
    data = info.get("data") if isinstance(info.get("data"), dict) else {}
    show = data.get("show") or {}
    base = data.get("base") or {}
    big = data.get("big") or {}
    other = data.get("other") or {}
    nlp = data.get("nlp") or {}
    special = data.get("special") or {}
    merge_jump = parse_merge_jump(show.get("merge_jump"))

    series_ids = to_int_list(base.get("cms_series_ids")) + to_int_list(base.get("cms_series_id"))
    series_names = to_text_list(base.get("cms_series_names")) + to_text_list(base.get("cms_series_name"))
    brand_names = to_text_list(base.get("car_brand_names")) + to_text_list(base.get("cms_brand_names"))
    tags = to_text_list(show.get("cms_tags")) + to_text_list(base.get("nlp_tags_choose2"))
    result_url = first_nonempty(
        show.get("jump_url2"),
        merge_jump.get("m_local_jump"),
        merge_jump.get("m_jump"),
        show.get("share_url"),
        show.get("pc_jump"),
        other.get("detail_url"),
    )

    return {
        "result_kind": classify_search_item(item, source_box),
        "card_type": item.get("type") or "",
        "source_box": source_box or {},
        "biz_type": info.get("biz_type"),
        "biz_id": info.get("biz_id"),
        "title": first_nonempty(show.get("title"), big.get("title2"), big.get("title"), base.get("title")),
        "summary": first_nonempty(big.get("summary"), other.get("description"), show.get("secondery_title")),
        "content_excerpt": first_nonempty(big.get("content"), big.get("summary"), other.get("description")),
        "author": first_nonempty(show.get("author")),
        "publish_time": first_nonempty(show.get("publish_time"), base.get("create_time")),
        "url": result_url,
        "series_ids": sorted({value for value in series_ids if value}),
        "series_names": sorted({value for value in series_names if value}),
        "brand_names": sorted({value for value in brand_names if value}),
        "tags": sorted({value for value in tags if value}),
        "score": info.get("score"),
        "match_keywords": sorted(
            {
                value
                for value in to_text_list(nlp.get("series"))
                + to_text_list(nlp.get("keyword"))
                + to_text_list(nlp.get("brand"))
                if value
            }
        ),
    }


def extract_first_match(pattern: str, text: str, flags: int = re.I | re.S) -> str:
    match = re.search(pattern, text, flags)
    return compact_text(match.group(1)) if match else ""


def extract_autohome_result_detail(url: str, keywords: list[str], include_raw: bool) -> dict[str, Any]:
    html_text = fetch_text(url, referer="https://sou.autohome.com.cn/")
    page_metadata = extract_page_metadata(html_text)
    detail: dict[str, Any] = {
        "url": url,
        "page_type": "unknown",
        "title": page_metadata.get("title", ""),
        "author": "",
        "publish_time": "",
        "content_text": "",
        "content_preview": "",
        "evidence_snippets": [],
        "page_metadata": page_metadata,
    }

    next_data_match = NEXT_DATA_RE.search(html_text)
    if next_data_match:
        next_data = json.loads(html.unescape(next_data_match.group(1)))
        page = str(next_data.get("page") or "")
        page_props = ((next_data.get("props") or {}).get("pageProps")) or {}

        if page == "/article/detail":
            author_info = first_mapping(page_props.get("authorInfo"))
            content_text = html_fragment_to_text(page_props.get("contentHtml") or "")
            detail.update(
                {
                    "page_type": "chejiahao_article",
                    "title": first_nonempty(page_props.get("articleTitle"), page_props.get("seoTitle"), detail["title"]),
                    "author": first_nonempty(
                        author_info.get("authorName"),
                        author_info.get("name"),
                        author_info.get("nickname"),
                    ),
                    "publish_time": first_nonempty(page_props.get("publishtime")),
                    "content_text": content_text,
                    "content_preview": truncate_text(content_text, 1600),
                    "series_relation_list": page_props.get("seriesRelationList") or [],
                }
            )
        elif page == "/bbs/detail":
            main_topic = page_props.get("mainTopic") or {}
            content_text = html_fragment_to_text(main_topic.get("t_content") or "")
            detail.update(
                {
                    "page_type": "club_topic",
                    "title": first_nonempty(main_topic.get("title"), detail["title"]),
                    "author": first_nonempty(main_topic.get("author"), main_topic.get("nickname")),
                    "publish_time": first_nonempty(main_topic.get("tdate")),
                    "content_text": content_text,
                    "content_preview": truncate_text(content_text, 1600),
                    "forum_name": first_nonempty(main_topic.get("bbsname")),
                    "forum_series_id": main_topic.get("bbsid"),
                }
            )
        if include_raw:
            detail["next_data_raw"] = next_data
    else:
        content_text = ""
        if "chejiahao" in url:
            content_text = first_nonempty(
                extract_first_match(r'<div class="describe">(.*?)</div>', html_text),
                extract_first_match(r'data-share-description="(.*?)"', html_text),
                page_metadata.get("description"),
            )
            detail.update(
                {
                    "page_type": "chejiahao_legacy",
                    "title": first_nonempty(
                        extract_first_match(r'<h1[^>]*id="desc_title"[^>]*>(.*?)</h1>', html_text),
                        detail["title"],
                    ),
                    "author": first_nonempty(
                        extract_first_match(r'<strong class="video-audio-authorName">\s*<a[^>]*>(.*?)</a>', html_text),
                        extract_first_match(r'<div class="authorInfo">.*?<a[^>]*>(.*?)</a>', html_text),
                    ),
                    "content_text": content_text,
                    "content_preview": truncate_text(content_text, 800),
                }
            )

    detail["evidence_snippets"] = extract_keyword_snippets(
        detail.get("title") or "",
        detail.get("content_text") or "",
        page_metadata.get("description") or "",
        keywords=keywords,
    )
    if not detail["content_preview"]:
        detail["content_preview"] = truncate_text(
            first_nonempty(detail.get("content_text"), page_metadata.get("description")),
            1600,
        )
    return detail


def enrich_search_results(results: list[dict[str, Any]], keywords: list[str], include_raw: bool) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for item in results:
        enriched_item = dict(item)
        url = str(item.get("url") or "").strip()
        if url.startswith(("http://", "https://")) and "autohome" in url:
            try:
                enriched_item["detail"] = extract_autohome_result_detail(url, keywords, include_raw)
            except Exception as exc:
                enriched_item["detail_error"] = str(exc)
        enriched.append(enriched_item)
    return enriched


def summarize_qp_result(qp_data: dict[str, Any]) -> dict[str, Any]:
    simple = qp_data.get("simple_result") or {}
    qp_result = qp_data.get("qp_result") or {}
    entity_result = simple.get("entity_result") or []
    query_intent = simple.get("queryintent") or qp_result.get("queryintent") or []

    series_items: list[dict[str, Any]] = []
    brand_names: list[str] = []
    entities: list[dict[str, Any]] = []

    for entity in entity_result:
        class_name = str(entity.get("class_name") or "")
        word = compact_text(entity.get("word") or entity.get("rawName"))
        std_name = compact_text(entity.get("s_word") or entity.get("entityName"))
        entities.append(
            {
                "class_name": class_name,
                "word": word,
                "standard_name": std_name,
                "type": entity.get("type"),
            }
        )
        if class_name == "CarSeries" or entity.get("type") == 4:
            series_items.append(
                {
                    "series_id": entity.get("id") if isinstance(entity.get("id"), int) else None,
                    "series_name": std_name or word,
                    "brand_names": [part for part in to_text_list(entity.get("belong_to_brand")) if part],
                }
            )
        for brand in to_text_list(entity.get("belong_to_brand")):
            if brand not in brand_names:
                brand_names.append(brand)

    for intent in query_intent:
        if intent.get("class_name") == "CarSeries" and compact_text(intent.get("entityName")):
            series_items.append(
                {
                    "series_id": intent.get("id") if isinstance(intent.get("id"), int) and intent.get("id") > 0 else None,
                    "series_name": compact_text(intent.get("entityName")),
                    "brand_names": [],
                }
            )

    deduped_series: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    for item in series_items:
        key = (item.get("series_id"), item.get("series_name") or "")
        if key in seen:
            continue
        seen.add(key)
        deduped_series.append(item)

    return {
        "raw_query": qp_result.get("query") or simple.get("query") or "",
        "correction": ((qp_result.get("correction") or {}).get("query") or ""),
        "entities": entities,
        "query_intent": query_intent,
        "inferred_series": deduped_series,
        "inferred_brands": brand_names,
    }


def extract_series_candidates_from_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str]] = set()
    for item in items:
        series_ids = item.get("series_ids") or []
        series_names = item.get("series_names") or []
        paired_names = list(series_names)
        if len(paired_names) < len(series_ids):
            paired_names.extend([""] * (len(series_ids) - len(paired_names)))
        for idx, series_id in enumerate(series_ids):
            series_name = paired_names[idx] if idx < len(paired_names) else ""
            key = (series_id, series_name)
            if key in seen:
                continue
            seen.add(key)
            candidates.append(
                {
                    "series_id": series_id,
                    "series_name": series_name,
                    "brand_names": item.get("brand_names") or [],
                }
            )
    return candidates


def search_autohome(query: str, max_results: int, cityid: str, include_raw: bool) -> dict[str, Any]:
    qp_data = fetch_json(
        QP_FULL_URL,
        params={"qptype": "1", "q": query},
        referer="https://sou.autohome.com.cn/",
    )
    qp_summary = summarize_qp_result(qp_data)
    search_data = fetch_json(
        SEARCH_URL,
        params={
            "uuid": uuid.uuid4().hex[:18],
            "source": "pc",
            "is_base_exp": 0,
            "pid": 90300023,
            "q": query,
            "offset": 0,
            "size": max_results,
            "page": 1,
            "ext": json.dumps(
                {
                    "chl": "",
                    "plat": "pc",
                    "pf": "h5",
                    "bbsId": "",
                    "q": query,
                    "offset": 0,
                    "size": max_results,
                    "modify": "0",
                    "cityid": cityid,
                    "perscont": "1",
                    "version": "1.0.3",
                    "box_count": 0,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
        referer="https://sou.autohome.com.cn/zonghe",
    )

    result = search_data.get("result") or {}
    flattened_items = flatten_search_items(result.get("itemlist") or [])
    normalized_items = [normalize_search_item(item, source_box) for item, source_box in flattened_items]
    enriched_items = enrich_search_results(normalized_items[:max_results], [query], include_raw)

    candidate_series: list[dict[str, Any]] = []
    seen_candidates: set[tuple[int | None, str]] = set()
    for item in qp_summary["inferred_series"] + extract_series_candidates_from_items(normalized_items):
        key = (item.get("series_id"), item.get("series_name") or "")
        if key in seen_candidates:
            continue
        seen_candidates.add(key)
        candidate_series.append(item)

    output = {
        "query": query,
        "qp_summary": qp_summary,
        "search_stats": {
            "rowcount": ((result.get("other") or {}).get("rowcount") or ""),
            "match_word": ((result.get("matchinfo") or {}).get("matchword") or ""),
            "match_word_id": ((result.get("matchinfo") or {}).get("matchwordid") or ""),
            "match_word_type": ((result.get("matchinfo") or {}).get("type64") or ""),
        },
        "candidate_series": candidate_series,
        "results": enriched_items,
    }
    if include_raw:
        output["qp_full_raw"] = qp_data
        output["search_raw"] = search_data
    return output


def collect_literal_hits(
    keywords: list[str],
    all_param_fields: dict[str, str],
    page_metadata: dict[str, str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    param_hits: list[dict[str, str]] = []
    page_hits: list[dict[str, str]] = []
    expanded_terms: list[str] = []
    for keyword in keywords:
        normalized = keyword.strip()
        if not normalized:
            continue
        if normalized not in expanded_terms:
            expanded_terms.append(normalized)
        for part in re.split(r"\s+", normalized):
            part = part.strip()
            if len(part) >= 2 and part not in expanded_terms:
                expanded_terms.append(part)

    for term in expanded_terms:
        for field, value in all_param_fields.items():
            haystack = f"{field} {value}"
            if term in haystack:
                param_hits.append({"keyword": term, "field": field, "value": value})
        for source_name, text in page_metadata.items():
            if term and text and term in text:
                page_hits.append({"keyword": term, "source": source_name, "text": text})
    return param_hits, page_hits


def fetch_series_bundle(series_id: int, keywords: list[str], include_raw: bool) -> dict[str, Any]:
    series_url = SERIES_URL.format(series_id=series_id)
    html_text = fetch_text(series_url, referer="https://www.autohome.com.cn/")
    page_metadata = extract_page_metadata(html_text)
    next_data = extract_next_data(html_text)

    base_info = (((next_data.get("props") or {}).get("pageProps")) or {}).get("seriesBaseInfo") or {}
    hot_spec_id = base_info.get("hotSpecId") or find_key(next_data, "hotSpecId")
    hot_spec_name = base_info.get("hotSpecName") or find_key(next_data, "hotSpecName") or ""

    output = {
        "series_id": series_id,
        "series_url": series_url,
        "series_name": base_info.get("seriesName") or base_info.get("name") or "",
        "brand_name": base_info.get("brandName") or "",
        "factory_name": base_info.get("fctName") or "",
        "level_name": base_info.get("levelName") or "",
        "page_energy_type": base_info.get("fueltypes") or "",
        "hot_spec_id": hot_spec_id,
        "hot_spec_name": hot_spec_name,
        "page_metadata": page_metadata,
        "matched_param_fields": {},
        "explicit_param_hits": [],
        "explicit_page_hits": [],
        "source_links": {"series_page": series_url},
    }

    if not hot_spec_id:
        return output

    param_json = fetch_json(
        PARAM_URL,
        params={"mode": 1, "site": 2, "specid": hot_spec_id},
        referer=series_url,
    )
    param_groups, all_param_fields, searchable_lines = build_param_groups(param_json, int(hot_spec_id))
    param_hits, page_hits = collect_literal_hits(keywords, all_param_fields, page_metadata)
    matched_fields = {}
    for hit in param_hits:
        matched_fields.setdefault(hit["field"], hit["value"])

    output.update(
        {
            "matched_param_fields": matched_fields,
            "explicit_param_hits": param_hits,
            "explicit_page_hits": page_hits,
            "source_links": {
                "series_page": series_url,
                "param_api": f"{PARAM_URL}?mode=1&site=2&specid={hot_spec_id}",
            },
        }
    )
    if include_raw:
        output["param_groups"] = param_groups
        output["all_param_fields"] = all_param_fields
        output["searchable_lines"] = searchable_lines
        output["next_data_raw"] = next_data
        output["param_raw"] = param_json
    return output


def choose_series_ids(
    explicit_series_ids: list[int],
    search_results: list[dict[str, Any]],
    max_series: int,
) -> list[int]:
    selected: list[int] = []
    seen: set[int] = set()

    for series_id in explicit_series_ids:
        if series_id not in seen:
            selected.append(series_id)
            seen.add(series_id)

    for payload in search_results:
        for item in payload.get("candidate_series") or []:
            series_id = item.get("series_id")
            if isinstance(series_id, int) and series_id > 0 and series_id not in seen:
                selected.append(series_id)
                seen.add(series_id)
            if len(selected) >= max_series:
                return selected
    return selected[:max_series]


def main() -> int:
    args = parse_args()
    keywords = [item.strip() for item in args.keywords if item.strip()]
    if not keywords:
        raise SystemExit("请先让 agent 生成关键词，再通过 --keyword 传入。")

    patent_context = load_patent_context(args.patent_json)

    # ── 搜索阶段：每个关键词单独 try/except，网络不通时记录错误继续 ──────────
    search_payloads = []
    for keyword in keywords:
        try:
            search_payloads.append(
                search_autohome(
                    query=keyword,
                    max_results=args.max_results,
                    cityid=args.cityid,
                    include_raw=args.include_raw,
                )
            )
        except Exception as exc:
            search_payloads.append({
                "query": keyword,
                "error": True,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "candidate_series": [],
            })

    series_ids = choose_series_ids(args.series_ids, search_payloads, args.max_series)

    # ── 车系抓取阶段：每个 series_id 单独 try/except ───────────────────────
    series_payloads = []
    for series_id in series_ids:
        try:
            series_payloads.append(fetch_series_bundle(series_id, keywords, args.include_raw))
        except Exception as exc:
            series_payloads.append({
                "series_id": series_id,
                "error": True,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            })

    output = {
        "source": "汽车之家",
        "topic_text": args.topic_text or "",
        "patent_context": patent_context,
        "explicit_search_terms": keywords,
        "search_queries": search_payloads,
        "selected_series_ids": series_ids,
        "series_evidence": series_payloads,
    }

    # 搜索全部失败且没有显式指定 series_id 时，给 agent 明确的后续指引
    all_search_failed = bool(search_payloads) and all(p.get("error") for p in search_payloads)
    if all_search_failed and not args.series_ids:
        output["agent_hint"] = (
            "汽车之家搜索接口（sou.autohome.com.cn）在当前网络环境下无法访问，"
            "搜索步骤已跳过。"
            "请根据专利主题自行判断目标竞品车系，通过 --series-id 参数重新调用本脚本，"
            "可直接抓取车系页和参数（www.autohome.com.cn 通常可正常访问）。"
            "例如：比亚迪汉=3837，海豹=5023，唐=735，宋Plus=4615。"
        )

    text = json.dumps(output, ensure_ascii=False, indent=2)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
