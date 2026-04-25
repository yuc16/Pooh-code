from __future__ import annotations

import base64
import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from .config import ImageGenerationConfig
from .output_files import OUTPUT_DIR, ensure_session_output_dir


@dataclass
class GeneratedImage:
    name: str
    media_type: str
    relative_path: str
    size: int


@dataclass
class ImageGenerationResult:
    model: str
    text: str
    images: list[GeneratedImage]
    raw: dict[str, Any]


_URL_PATTERN = re.compile(r"https?://[^\s'\"<>()\]]+", re.IGNORECASE)
_IMAGE_EXT_PATTERN = re.compile(r"\.(png|jpe?g|gif|webp|bmp|svg)(?:$|[?#])", re.IGNORECASE)


# 模型能力元数据：让前端按模型动态切比例 / 清晰度 / 图生图 UI。
# kind: "chat"  → 走 AIHubMix /v1/chat/completions（aspect 是提示词，不能调清晰度）
#       "apimart" → 走 apimart /v1/images/generations（异步任务，size + resolution 是真参数，支持 image_urls）
MODEL_CAPABILITIES: dict[str, dict[str, Any]] = {
    "web-gpt-image-2-vip": {
        "kind": "chat",
        "ratios": ["1:1", "2:3", "3:2"],
        "resolutions": [],
        "supports_reference": False,
    },
    "gemini-3.1-flash-image-preview-free": {
        "kind": "chat",
        "ratios": ["1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9"],
        "resolutions": [],
        "supports_reference": False,
    },
    "gpt-image-2": {
        "kind": "apimart",
        "ratios": [
            "1:1", "3:2", "2:3", "4:3", "3:4", "5:4", "4:5",
            "16:9", "9:16", "2:1", "1:2", "21:9", "9:21", "auto",
        ],
        "resolutions": ["1k", "2k", "4k"],
        "supports_reference": True,
    },
}


def get_model_capabilities(model: str) -> dict[str, Any]:
    return MODEL_CAPABILITIES.get(model, {
        "kind": "chat",
        "ratios": ["1:1"],
        "resolutions": [],
        "supports_reference": False,
    })


def model_capabilities_payload() -> dict[str, dict[str, Any]]:
    return {name: dict(caps) for name, caps in MODEL_CAPABILITIES.items()}


def _ext_for_media_type(media_type: str) -> str:
    guessed = mimetypes.guess_extension(media_type or "")
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".png"


def _allocate_output_path(out_dir: Path, ext: str, next_index: int) -> tuple[Path, int]:
    while True:
        filename = f"image-gen-{next_index:02d}{ext}"
        target = out_dir / filename
        if not target.exists():
            return target, next_index + 1
        next_index += 1


def _looks_like_image_url(url: str) -> bool:
    return bool(_IMAGE_EXT_PATTERN.search(url))


def _download_image_urls(
    urls: list[str],
    out_dir: Path,
    next_index: int,
) -> tuple[list[GeneratedImage], int]:
    results: list[GeneratedImage] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        try:
            resp = requests.get(url, timeout=120, stream=True)
            resp.raise_for_status()
        except Exception:
            continue
        media_type = (resp.headers.get("Content-Type") or "").split(";", 1)[0].strip()
        if not media_type or not media_type.startswith("image/"):
            if not _looks_like_image_url(url):
                continue
            media_type = mimetypes.guess_type(url)[0] or "image/png"
        binary = resp.content
        if not binary:
            continue
        target, next_index = _allocate_output_path(
            out_dir, _ext_for_media_type(media_type), next_index
        )
        target.write_bytes(binary)
        results.append(
            GeneratedImage(
                name=target.name,
                media_type=media_type,
                relative_path=str(target.relative_to(OUTPUT_DIR)),
                size=len(binary),
            )
        )
    return results, next_index


def _strip_image_urls(text: str, urls: list[str]) -> str:
    stripped = text
    stripped = re.sub(r"!\s*\[[^\]]*\]\s*\([^)]*\)", "", stripped)
    stripped = re.sub(r"\[[^\]]*\]\s*\(https?://[^)\s]+\)", "", stripped)
    for url in urls:
        stripped = stripped.replace(url, "")
    stripped = re.sub(r"!\s*\[[^\]]*\]\s*\(\s*\)", "", stripped)
    stripped = re.sub(r"!\s*\(\s*\)", "", stripped)
    stripped = re.sub(r"\[\s*\]\s*\(\s*\)", "", stripped)
    return re.sub(r"\n{3,}", "\n\n", stripped).strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_dict_in_list(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _extract_task_id(payload: Any) -> str | None:
    """apimart 提交响应有时是顶层平铺，有时把 task_id 包在 data 里（dict 或 list[dict]）。"""
    if not isinstance(payload, dict):
        return None
    candidate = payload.get("task_id") or payload.get("id")
    if candidate:
        return str(candidate)
    data = payload.get("data")
    nested = _as_dict(data) or _first_dict_in_list(data)
    candidate = nested.get("task_id") or nested.get("id")
    return str(candidate) if candidate else None


def _extract_task_status(payload: dict[str, Any]) -> str:
    nested = _as_dict(payload.get("data")) or _first_dict_in_list(payload.get("data"))
    raw = (
        payload.get("status")
        or payload.get("state")
        or nested.get("status")
        or nested.get("state")
        or ""
    )
    return str(raw).lower()


def _extract_result_block(payload: dict[str, Any] | None) -> dict[str, Any]:
    """在 payload 任意层级里找一个含 `images: list[...]` 的 dict 节点。

    apimart 返回的实际嵌套是 `payload.data.result.images`，但官方文档示例又写成
    顶层 `result.images`，两种都见过；同时 `data` 偶尔会是 `list[dict]`。这里用
    BFS 一次性把所有形态都覆盖掉。
    """
    if not isinstance(payload, dict):
        return {}
    queue: list[Any] = [payload]
    while queue:
        node = queue.pop(0)
        if isinstance(node, dict):
            images = node.get("images")
            if isinstance(images, list) and images:
                return node
            for value in node.values():
                if isinstance(value, (dict, list)):
                    queue.append(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    queue.append(item)
    # 兜底返回最有可能的 dict 节点，给上游一个最后的解析机会
    for key in ("result", "data"):
        block = payload.get(key)
        nested = _as_dict(block) or _first_dict_in_list(block)
        if nested:
            return nested
    return _as_dict(payload)


def _has_image_urls(payload: dict[str, Any]) -> bool:
    block = _extract_result_block(payload)
    images = block.get("images") if isinstance(block, dict) else None
    return bool(images)


def _find_first_error_message(payload: Any) -> str:
    """BFS 找一段非空的错误描述，覆盖 apimart 把错误埋在不同字段的几种风格。"""
    if not isinstance(payload, (dict, list)):
        return ""
    keys = ("error_message", "errorMessage", "fail_reason", "failReason", "reason", "error", "message", "msg", "detail")
    queue: list[Any] = [payload]
    while queue:
        node = queue.pop(0)
        if isinstance(node, dict):
            for key in keys:
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    nested = value.get("message") or value.get("detail") or value.get("error")
                    if isinstance(nested, str) and nested.strip():
                        return nested.strip()
            for value in node.values():
                if isinstance(value, (dict, list)):
                    queue.append(value)
        elif isinstance(node, list):
            for item in node:
                if isinstance(item, (dict, list)):
                    queue.append(item)
    return ""


def _read_reference_as_data_uri(rel_path: str) -> str | None:
    rel = (rel_path or "").strip()
    if not rel:
        return None
    candidate = (OUTPUT_DIR / rel).resolve()
    try:
        candidate.relative_to(OUTPUT_DIR.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    media_type = mimetypes.guess_type(candidate.name)[0] or "image/png"
    if not media_type.startswith("image/"):
        return None
    encoded = base64.b64encode(candidate.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def generate_images(
    cfg: ImageGenerationConfig,
    *,
    prompt: str,
    session_id: str,
    aspect_ratio: str | None = None,
    model: str | None = None,
    resolution: str | None = None,
    reference_image_paths: list[str] | None = None,
) -> ImageGenerationResult:
    selected_model = (model or cfg.model or "").strip() or cfg.model
    if cfg.models and selected_model not in cfg.models:
        raise ValueError(f"不支持的图片模型: {selected_model}")

    caps = get_model_capabilities(selected_model)
    actual_ratio = (aspect_ratio or cfg.default_aspect_ratio or "1:1").strip() or "1:1"
    actual_resolution = (resolution or cfg.default_resolution or "1k").strip() or "1k"
    out_dir = ensure_session_output_dir(session_id)

    image_uris: list[str] = []
    if reference_image_paths and caps.get("supports_reference"):
        for rel in reference_image_paths:
            data_uri = _read_reference_as_data_uri(rel)
            if data_uri:
                image_uris.append(data_uri)

    if caps.get("kind") == "apimart":
        return _generate_via_apimart(
            cfg,
            prompt=prompt,
            selected_model=selected_model,
            out_dir=out_dir,
            size=actual_ratio,
            resolution=actual_resolution,
            image_urls=image_uris,
        )

    return _generate_via_chat(
        cfg,
        prompt=prompt,
        selected_model=selected_model,
        out_dir=out_dir,
        aspect_ratio=actual_ratio,
    )


def _generate_via_chat(
    cfg: ImageGenerationConfig,
    *,
    prompt: str,
    selected_model: str,
    out_dir: Path,
    aspect_ratio: str,
) -> ImageGenerationResult:
    api_key = (cfg.api_key or "").strip()
    if not api_key:
        raise ValueError("未配置图片生成 API Key")

    base_url = (cfg.base_url or "https://aihubmix.com/v1").rstrip("/")
    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": f"aspect_ratio={aspect_ratio}"},
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
        "modalities": ["text", "image"],
    }

    resp = requests.post(
        f"{base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    try:
        data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"图片生成服务返回了不可解析的响应: HTTP {resp.status_code}") from exc
    if resp.status_code >= 400:
        msg = ""
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message") or "")
            elif err:
                msg = str(err)
        raise RuntimeError(msg or f"图片生成失败: HTTP {resp.status_code}")

    choice = ((data.get("choices") or [{}])[0] if isinstance(data, dict) else {}) or {}
    message = choice.get("message") or {}
    parts = message.get("multi_mod_content") or []
    if not isinstance(parts, list):
        parts = []

    text_chunks: list[str] = []
    images: list[GeneratedImage] = []
    next_index = 1

    for part in parts:
        if not isinstance(part, dict):
            continue
        part_text = str(part.get("text") or "").strip()
        if part_text:
            text_chunks.append(part_text)
        inline = part.get("inline_data") or {}
        raw_b64 = str(inline.get("data") or "").strip()
        if not raw_b64:
            continue
        media_type = str(inline.get("mime_type") or "image/png").strip() or "image/png"
        binary = base64.b64decode(raw_b64)
        target, next_index = _allocate_output_path(
            out_dir, _ext_for_media_type(media_type), next_index
        )
        target.write_bytes(binary)
        images.append(
            GeneratedImage(
                name=target.name,
                media_type=media_type,
                relative_path=str(target.relative_to(OUTPUT_DIR)),
                size=len(binary),
            )
        )

    raw_content = message.get("content")
    content_text = ""
    if isinstance(raw_content, str):
        content_text = raw_content
    elif isinstance(raw_content, list):
        chunks = []
        for item in raw_content:
            if isinstance(item, dict) and item.get("type") == "text":
                chunks.append(str(item.get("text") or ""))
        content_text = "\n".join(chunk for chunk in chunks if chunk)

    if not images and content_text:
        urls = _URL_PATTERN.findall(content_text)
        image_urls: list[str] = []
        seen_urls: set[str] = set()
        for raw in urls:
            cleaned = raw.rstrip(".,;:)}")
            if cleaned in seen_urls or not _looks_like_image_url(cleaned):
                continue
            seen_urls.add(cleaned)
            image_urls.append(cleaned)
        if image_urls:
            primary_urls = image_urls[:1]
            downloaded, next_index = _download_image_urls(primary_urls, out_dir, next_index)
            images.extend(downloaded)
            if downloaded:
                remaining = _strip_image_urls(content_text, image_urls)
                if remaining:
                    text_chunks.append(remaining)

    final_text = "\n\n".join(chunk for chunk in text_chunks if chunk).strip()
    if not final_text:
        final_text = content_text.strip()
    if not images:
        raise RuntimeError("图片生成服务没有返回图片")

    return ImageGenerationResult(
        model=str(data.get("model") or selected_model),
        text=final_text,
        images=images,
        raw=data if isinstance(data, dict) else {},
    )


def _generate_via_apimart(
    cfg: ImageGenerationConfig,
    *,
    prompt: str,
    selected_model: str,
    out_dir: Path,
    size: str,
    resolution: str,
    image_urls: list[str],
) -> ImageGenerationResult:
    api_key = (cfg.apimart_api_key or "").strip()
    if not api_key:
        raise ValueError("未配置 apimart API Key（settings.json 里的 image.apimart_api_key）")
    base_url = (cfg.apimart_base_url or "https://api.apimart.ai/v1").rstrip("/")
    payload: dict[str, Any] = {
        "model": selected_model,
        "prompt": prompt,
        "n": 1,
        "size": size,
        "resolution": resolution,
    }
    if image_urls:
        payload["image_urls"] = image_urls

    resp = requests.post(
        f"{base_url}/images/generations",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=180,
    )
    try:
        submit_data = resp.json()
    except Exception as exc:
        raise RuntimeError(f"apimart 接口返回了不可解析的响应: HTTP {resp.status_code}") from exc
    if resp.status_code >= 400:
        msg = _find_first_error_message(submit_data)
        raise RuntimeError(
            (msg or f"apimart 提交任务失败: HTTP {resp.status_code}")
            + f" | 原始响应: {submit_data}"
        )

    task_id = _extract_task_id(submit_data)
    if not task_id:
        raise RuntimeError(f"apimart 提交任务未返回 task_id: {submit_data}")

    poll_url = f"{base_url}/tasks/{task_id}"
    deadline = time.time() + 300
    interval = 3.0
    final_payload: dict[str, Any] | None = None
    while True:
        if time.time() > deadline:
            raise RuntimeError(f"apimart 任务超时（5 分钟未完成），task_id={task_id}")
        try:
            poll_resp = requests.get(
                poll_url,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30,
            )
            poll_data = poll_resp.json()
        except Exception:
            time.sleep(interval)
            continue
        if poll_resp.status_code >= 400:
            raise RuntimeError(
                f"apimart 任务查询失败 HTTP {poll_resp.status_code}: {poll_data}"
            )
        if not isinstance(poll_data, dict):
            time.sleep(interval)
            continue
        status = _extract_task_status(poll_data)
        if status in {"success", "succeeded", "completed", "finished", "ok"}:
            final_payload = poll_data
            break
        if status in {"failed", "error", "cancelled", "canceled"}:
            err = _find_first_error_message(poll_data) or "未知错误"
            raise RuntimeError(f"apimart 任务失败: {err} | 原始响应: {poll_data}")
        if not status and (poll_data.get("result") or _has_image_urls(poll_data)):
            final_payload = poll_data
            break
        time.sleep(interval)

    result_block = _extract_result_block(final_payload)
    image_entries = result_block.get("images") or []
    out_urls: list[str] = []
    for entry in image_entries:
        if not isinstance(entry, dict):
            continue
        url_field = entry.get("url")
        if isinstance(url_field, list):
            for item in url_field:
                if isinstance(item, str) and item.strip():
                    out_urls.append(item.strip())
        elif isinstance(url_field, str) and url_field.strip():
            out_urls.append(url_field.strip())
    if not out_urls:
        raise RuntimeError(f"apimart 任务完成但未返回图片 URL: {final_payload}")

    primary_urls = out_urls[:1]
    downloaded, _ = _download_image_urls(primary_urls, out_dir, 1)
    if not downloaded:
        raise RuntimeError("apimart 图片下载失败")

    return ImageGenerationResult(
        model=selected_model,
        text="",
        images=downloaded,
        raw=final_payload,
    )
