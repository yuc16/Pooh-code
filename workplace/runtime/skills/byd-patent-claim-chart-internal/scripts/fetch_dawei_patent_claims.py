#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


URL = "https://pat.daweisoft.com/api/innojoy-search/api/v1/patent/search"
TAG_RE = re.compile(r"<[^>]+>")
SECRETS_PATH = Path(__file__).resolve().parent.parent / "secrets.local.json"
BYD_OWNER_KEYWORDS = [
    "比亚迪",
    "BYD",
    "BYD CO LTD",
    "BYD COMPANY",
    "比亚迪股份有限公司",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从大为专利精确拉权利要求，或按关键词检索比亚迪中文有权专利。"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--pnm",
        "--patent-no",
        dest="pnm",
        help="专利公开号，例如 CN114512759B；支持 --pnm 和 --patent-no 两种写法",
    )
    mode.add_argument(
        "--keyword",
        dest="keywords",
        action="append",
        help="可重复传入；用于检索比亚迪中文有权专利的关键词",
    )
    parser.add_argument("--page-num", type=int, default=1, help="关键词检索页码，默认 1")
    parser.add_argument("--page-size", type=int, default=10, help="关键词检索每页条数，默认 10")
    parser.add_argument(
        "--with-claims",
        action="store_true",
        help="关键词检索时，顺带为前若干条结果补抓权利要求摘要",
    )
    parser.add_argument(
        "--claims-limit",
        type=int,
        default=3,
        help="关键词检索时，最多为多少条结果补抓权利要求，默认 3",
    )
    parser.add_argument("--output", help="输出 JSON 路径；不传则打印到标准输出")
    return parser.parse_args()


def build_headers() -> dict[str, str]:
    token = os.environ.get("DAWEISOFT_TOKEN", "").strip()
    device_id = os.environ.get("DAWEISOFT_DEVICE_ID", "").strip()
    if SECRETS_PATH.exists():
        try:
            secret_data = json.loads(SECRETS_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"无法解析 {SECRETS_PATH}: {exc}") from exc
        token = token or str(secret_data.get("DAWEISOFT_TOKEN", "")).strip()
        device_id = device_id or str(secret_data.get("DAWEISOFT_DEVICE_ID", "")).strip()
    if not token or not device_id:
        raise SystemExit("缺少 DAWEISOFT_TOKEN 或 DAWEISOFT_DEVICE_ID。")
    return {
        "Content-Type": "application/json;charset=UTF-8",
        "Origin": "https://pat.daweisoft.com",
        "Referer": "https://pat.daweisoft.com/searchresult",
        "X-Group-Env": "PAT",
        "token": token,
        "deviceId": device_id,
        "User-Agent": "Mozilla/5.0",
    }


def post_payload(payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    req = Request(
        URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def build_detail_payload(pnm: str) -> dict[str, Any]:
    return {
        "query": f"PNM={pnm}",
        "oriQuery": f"PNM={pnm}",
        "databases": [],
        "dbTypes": ["fmzl", "fmsq", "xx", "wg"],
        "pageNum": 1,
        "pageSize": 1,
        "sortBy": "-Relevant",
        "fields": "PNM,TI,PA,CAS,INN,AD,CC,CLS,CLMN,CLM,CL",
        "searchType": "baseinfo_detail",
    }


def build_search_query(keywords: list[str]) -> str:
    cleaned = [item.strip() for item in (keywords or []) if item and item.strip()]
    if not cleaned:
        raise SystemExit("关键词检索模式下至少需要一个 --keyword。")
    terms = [f"({item})" for item in cleaned]
    terms.append("CAS=(比亚迪)")
    terms.append("CC=(CN)")
    return " AND ".join(terms)


def build_search_payload(keywords: list[str], page_num: int, page_size: int) -> dict[str, Any]:
    query = build_search_query(keywords)
    return {
        "query": query,
        "oriQuery": query,
        "databases": [],
        "dbTypes": ["fmzl", "fmsq", "xx", "wg"],
        "pageNum": page_num,
        "pageSize": page_size,
        "sortBy": "-Relevant",
        "fields": "PTS,DPIStar,PNM,TI,CLS,PA,AN,AD,INN,CC,CAS,AB,APD,APN",
        "searchType": "patent_list",
    }


def strip_tags(text: str) -> str:
    text = TAG_RE.sub("", str(text or ""))
    text = re.sub(r"[ \t]*\r?\n[ \t]*", "\n", text).strip()
    return re.sub(r"\n{2,}", "\n", text)


def normalize_text(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("TIZH", "TIEN", "TIOL", "TIJA", "title"):
            text = value.get(key)
            if text:
                return strip_tags(text)
        return strip_tags(json.dumps(value, ensure_ascii=False))
    if isinstance(value, list):
        return "；".join(part for part in (normalize_text(item) for item in value) if part)
    return strip_tags(value)


def normalize_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [text for text in (normalize_text(item) for item in items) if text]


def contains_byd(text: str) -> bool:
    upper = text.upper()
    raw = text
    return any(keyword in raw or keyword.upper() in upper for keyword in BYD_OWNER_KEYWORDS)


def parse_detail_record(record: dict[str, Any]) -> dict[str, Any]:
    claim_block = record.get("CL") or {}
    assignee = normalize_text(record.get("CAS", ""))
    applicant = normalize_text(record.get("PA", ""))
    country_code = normalize_text(record.get("CC", "")).upper()
    return {
        "patent_no": normalize_text(record.get("PNM", "")),
        "title": normalize_text(record.get("TI", "")),
        "applicant": applicant,
        "assignee": assignee,
        "inventor": normalize_text(record.get("INN", "")),
        "application_date": normalize_text(record.get("AD", "")),
        "country_code": country_code,
        "classification": normalize_text(record.get("CLS", "")),
        "claim_count": record.get("CLMN", 0),
        "main_claim": normalize_text(record.get("CLM", "")),
        "claims_zh": normalize_list(claim_block.get("CLZH")),
        "claims_en": normalize_list(claim_block.get("CLOL")),
        "ownership_check": {
            "country_is_cn": country_code == "CN",
            "assignee_matches_byd": contains_byd(assignee),
            "applicant_matches_byd": contains_byd(applicant),
        },
        "source": "大为专利",
        "source_url": "https://pat.daweisoft.com/searchresult",
    }


def parse_search_record(record: dict[str, Any]) -> dict[str, Any]:
    assignee = normalize_text(record.get("CAS", ""))
    applicant = normalize_text(record.get("PA", ""))
    country_code = normalize_text(record.get("CC", "")).upper()
    owner_match = {
        "country_is_cn": country_code == "CN",
        "assignee_matches_byd": contains_byd(assignee),
        "applicant_matches_byd": contains_byd(applicant),
    }
    return {
        "patent_no": normalize_text(record.get("PNM", "")),
        "title": normalize_text(record.get("TI", "")),
        "applicant": applicant,
        "assignee": assignee,
        "inventor": normalize_text(record.get("INN", "")),
        "application_date": normalize_text(record.get("AD", "")),
        "country_code": country_code,
        "classification": normalize_text(record.get("CLS", "")),
        "abstract": normalize_text(record.get("AB", "")),
        "application_no": normalize_text(record.get("APN", "")),
        "application_publish_date": normalize_text(record.get("APD", "")),
        "ownership_check": owner_match,
        "is_byd_cn_owned": owner_match["country_is_cn"] and owner_match["assignee_matches_byd"],
    }


def fetch_detail_by_pnm(pnm: str, headers: dict[str, str]) -> dict[str, Any]:
    data = post_payload(build_detail_payload(pnm), headers)
    patent_list = ((data.get("data") or {}).get("patentList")) or []
    if not patent_list:
        raise SystemExit(f"未找到 {pnm} 对应记录。")
    output = parse_detail_record(patent_list[0])
    output["mode"] = "patent_detail"
    return output


def fetch_search_by_keywords(args: argparse.Namespace, headers: dict[str, str]) -> dict[str, Any]:
    payload = build_search_payload(args.keywords or [], args.page_num, args.page_size)
    data = post_payload(payload, headers)
    patent_list = ((data.get("data") or {}).get("patentList")) or []
    parsed_records = [parse_search_record(record) for record in patent_list]
    matched_records = [record for record in parsed_records if record["is_byd_cn_owned"]]

    if args.with_claims:
        for record in matched_records[: max(args.claims_limit, 0)]:
            try:
                record["claim_snapshot"] = fetch_detail_by_pnm(record["patent_no"], headers)
            except SystemExit as exc:
                record["claim_snapshot_error"] = str(exc)

    return {
        "mode": "keyword_search",
        "source": "大为专利",
        "source_url": "https://pat.daweisoft.com/searchresult",
        "hard_constraints": {
            "country_code": "CN",
            "owner_must_match": "比亚迪",
            "enforced_query": {
                "query": payload["query"],
                "search_type": payload["searchType"],
            },
            "post_filter": "仅保留 CC=CN 且 CAS 命中比亚迪的记录",
        },
        "search_terms": [item.strip() for item in (args.keywords or []) if item and item.strip()],
        "page_num": args.page_num,
        "page_size": args.page_size,
        "raw_result_count": len(parsed_records),
        "result_count": len(matched_records),
        "patents": matched_records,
    }


def main() -> int:
    args = parse_args()
    headers = build_headers()
    if args.pnm:
        output = fetch_detail_by_pnm(args.pnm, headers)
    else:
        output = fetch_search_by_keywords(args, headers)

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
