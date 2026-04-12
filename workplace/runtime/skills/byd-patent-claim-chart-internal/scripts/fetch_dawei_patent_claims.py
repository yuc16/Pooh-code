#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen


URL = "https://pat.daweisoft.com/api/innojoy-search/api/v1/patent/search"
TAG_RE = re.compile(r"<[^>]+>")
SECRETS_PATH = Path(__file__).resolve().parent.parent / "secrets.local.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从大为专利按公开号获取专利与权利要求。")
    parser.add_argument("--pnm", required=True, help="专利公开号，例如 CN114512759B")
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


def build_payload(pnm: str) -> bytes:
    payload = {
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
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


def strip_tags(text: str) -> str:
    text = TAG_RE.sub("", text or "")
    text = re.sub(r"[ \t]*\r?\n[ \t]*", "\n", text).strip()
    return re.sub(r"\n{2,}", "\n", text)


def normalize_list(value) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [text for text in (strip_tags(str(item)) for item in items) if text]


def main() -> int:
    args = parse_args()
    req = Request(URL, data=build_payload(args.pnm), headers=build_headers(), method="POST")
    with urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="replace"))

    patent_list = ((data.get("data") or {}).get("patentList")) or []
    if not patent_list:
        raise SystemExit(f"未找到 {args.pnm} 对应记录。")

    record = patent_list[0]
    claim_block = record.get("CL") or {}
    output = {
        "patent_no": record.get("PNM", ""),
        "title": record.get("TI", ""),
        "applicant": record.get("PA", ""),
        "assignee": record.get("CAS", ""),
        "inventor": record.get("INN", ""),
        "application_date": record.get("AD", ""),
        "classification": record.get("CLS", ""),
        "claim_count": record.get("CLMN", 0),
        "main_claim": strip_tags(str(record.get("CLM", "") or "")),
        "claims_zh": normalize_list(claim_block.get("CLZH")),
        "claims_en": normalize_list(claim_block.get("CLOL")),
        "source": "大为专利",
        "source_url": "https://pat.daweisoft.com/searchresult",
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
