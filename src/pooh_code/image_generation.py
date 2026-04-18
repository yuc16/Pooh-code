from __future__ import annotations

import base64
import mimetypes
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


def _ext_for_media_type(media_type: str) -> str:
    guessed = mimetypes.guess_extension(media_type or "")
    if guessed == ".jpe":
        return ".jpg"
    return guessed or ".png"


def generate_images(
    cfg: ImageGenerationConfig,
    *,
    prompt: str,
    session_id: str,
    aspect_ratio: str | None = None,
) -> ImageGenerationResult:
    api_key = (cfg.api_key or "").strip()
    if not api_key:
        raise ValueError("未配置图片生成 API Key")

    actual_ratio = (aspect_ratio or cfg.default_aspect_ratio or "1:1").strip() or "1:1"
    base_url = (cfg.base_url or "https://aihubmix.com/v1").rstrip("/")
    payload = {
        "model": cfg.model,
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
        filename = f"image-gen-{next_index:02d}{_ext_for_media_type(media_type)}"
        target = out_dir / filename
        while target.exists():
            next_index += 1
            filename = f"image-gen-{next_index:02d}{_ext_for_media_type(media_type)}"
            target = out_dir / filename
        target.write_bytes(binary)
        images.append(
            GeneratedImage(
                name=filename,
                media_type=media_type,
                relative_path=str(target.relative_to(OUTPUT_DIR)),
                size=len(binary),
            )
        )
        next_index += 1

    fallback_text = str(message.get("content") or "").strip()
    final_text = "\n\n".join(chunk for chunk in text_chunks if chunk).strip() or fallback_text
    if not images:
        raise RuntimeError("图片生成服务没有返回图片")

    return ImageGenerationResult(
        model=str(data.get("model") or cfg.model),
        text=final_text,
        images=images,
        raw=data if isinstance(data, dict) else {},
    )
