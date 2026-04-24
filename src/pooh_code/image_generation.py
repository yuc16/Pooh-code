from __future__ import annotations

import base64
import mimetypes
import re
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


def generate_images(
    cfg: ImageGenerationConfig,
    *,
    prompt: str,
    session_id: str,
    aspect_ratio: str | None = None,
    model: str | None = None,
) -> ImageGenerationResult:
    api_key = (cfg.api_key or "").strip()
    if not api_key:
        raise ValueError("未配置图片生成 API Key")

    actual_ratio = (aspect_ratio or cfg.default_aspect_ratio or "1:1").strip() or "1:1"
    base_url = (cfg.base_url or "https://aihubmix.com/v1").rstrip("/")
    selected_model = (model or cfg.model or "").strip() or cfg.model
    if cfg.models and selected_model not in cfg.models:
        raise ValueError(f"不支持的图片模型: {selected_model}")
    payload = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": f"aspect_ratio={actual_ratio}"},
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
    out_dir = ensure_session_output_dir(session_id)
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
