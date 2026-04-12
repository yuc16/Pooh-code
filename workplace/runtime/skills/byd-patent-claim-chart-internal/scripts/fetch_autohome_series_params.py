#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SERIES_URL = "https://www.autohome.com.cn/{series_id}"
PARAM_URL = "https://www.autohome.com.cn/web-main/car/param/getParamConf"
NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
BATTERY_FIELDS = [
    "能源类型",
    "电池类型",
    "电芯品牌",
    "电池能量(kWh)",
    "电池能量密度(Wh/kg)",
    "CLTC纯电续航里程(km)",
    "百公里耗电量(kWh/100km)",
    "快充功能",
    "电池快充时间(小时)",
    "电池慢充时间(小时)",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从汽车之家获取指定车系的代表车型参数。")
    parser.add_argument("--series-id", required=True, type=int, help="汽车之家车系 ID")
    parser.add_argument("--output", help="输出 JSON 路径；不传则打印到标准输出")
    return parser.parse_args()


def fetch_text(url: str, params: dict | None = None) -> str:
    full_url = f"{url}?{urlencode(params)}" if params else url
    req = Request(full_url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.autohome.com.cn/"})
    with urlopen(req, timeout=30) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def find_key(node, key: str):
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


def title_map(title_list: list[dict]) -> dict[int, str]:
    mapping: dict[int, str] = {}
    for group in title_list:
        for item in group.get("items", []):
            title_id = item.get("titleid")
            name = item.get("itemname")
            if isinstance(title_id, int) and name:
                mapping[title_id] = str(name)
    return mapping


def normalize_value(item: dict) -> str:
    value = str(item.get("itemname") or "").strip()
    if value and value != "-":
        return value
    parts = []
    for sub in item.get("sublist") or []:
        name = str(sub.get("name") or "").strip()
        sub_value = str(sub.get("value") or "").strip()
        if name and sub_value and sub_value not in {"●", "○"}:
            parts.append(f"{name}:{sub_value}")
        elif name:
            parts.append(name)
        elif sub_value:
            parts.append(sub_value)
    return "；".join(parts)


def main() -> int:
    args = parse_args()
    series_url = SERIES_URL.format(series_id=args.series_id)
    html_text = fetch_text(series_url)
    match = NEXT_DATA_RE.search(html_text)
    if not match:
        raise SystemExit("未找到 __NEXT_DATA__。")
    next_data = json.loads(html.unescape(match.group(1)))

    hot_spec_id = find_key(next_data, "hotSpecId")
    if not hot_spec_id:
        raise SystemExit("未找到 hotSpecId。")

    param_json = json.loads(fetch_text(PARAM_URL, {"mode": 1, "site": 2, "specid": hot_spec_id}))
    result = param_json.get("result") or {}
    mapping = title_map(result.get("titlelist") or [])
    datalist = result.get("datalist") or []
    spec = next((item for item in datalist if item.get("specid") == hot_spec_id), datalist[0] if datalist else {})

    values: dict[str, str] = {}
    for item in spec.get("paramconflist") or []:
        field = mapping.get(item.get("titleid"))
        if field and field not in values:
            parsed = normalize_value(item)
            if parsed:
                values[field] = parsed

    base_info = (((next_data.get("props") or {}).get("pageProps")) or {}).get("seriesBaseInfo") or {}
    output = {
        "series_id": args.series_id,
        "series_url": series_url,
        "series_name": base_info.get("seriesName") or base_info.get("name") or "",
        "brand_name": base_info.get("brandName") or "",
        "factory_name": base_info.get("fctName") or "",
        "hot_spec_id": hot_spec_id,
        "hot_spec_name": base_info.get("hotSpecName") or find_key(next_data, "hotSpecName") or "",
        "battery_fields": {field: values.get(field, "") for field in BATTERY_FIELDS},
        "source": "汽车之家",
        "source_links": {
            "series_page": series_url,
            "param_api": f"{PARAM_URL}?mode=1&site=2&specid={hot_spec_id}",
        },
    }

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
