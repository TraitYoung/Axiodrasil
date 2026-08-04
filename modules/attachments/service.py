"""Solo 附件消化：文本读入 + 图片经 DashScope VL 描述成文字。"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import Literal

from openai import OpenAI

from observability import obs

MAX_BYTES = 5 * 1024 * 1024
TEXT_MAX_CHARS = 8000

TEXT_EXTS = {".txt", ".md", ".markdown", ".json", ".csv", ".log"}
TEXT_MIMES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/json",
    "application/csv",
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

Kind = Literal["text", "image"]


@dataclass(frozen=True)
class IngestResult:
    name: str
    kind: Kind
    text: str
    truncated: bool


class AttachmentError(ValueError):
    """可映射为 HTTP 4xx/503 的业务错误。"""

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _ext(name: str) -> str:
    base = (name or "").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." not in base:
        return ""
    return "." + base.rsplit(".", 1)[-1].lower()


def _mime_for_image(ext: str, content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in IMAGE_MIMES:
        return ct
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(ext, "image/png")


def _classify(name: str, content_type: str) -> Kind:
    ext = _ext(name)
    ct = (content_type or "").split(";")[0].strip().lower()
    if ext in TEXT_EXTS or ct in TEXT_MIMES:
        return "text"
    if ext in IMAGE_EXTS or ct in IMAGE_MIMES:
        return "image"
    raise AttachmentError(
        f"暂不支持该类型（{name or '未命名'}）。请上传 txt/md/json/csv 或 png/jpg/webp/gif。"
    )


def _qwen_creds() -> tuple[str, str]:
    key = (os.getenv("QWEN_API_KEY") or "").strip()
    base = (
        os.getenv("QWEN_BASE_URL")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    ).strip()
    return key, base.rstrip("/")


def _describe_image(data: bytes, *, name: str, content_type: str) -> str:
    key, base = _qwen_creds()
    if not key:
        raise AttachmentError(
            "图片需要 QWEN_API_KEY（DashScope）做视觉描述，请在 .env 配置后重试。",
            status_code=503,
        )
    model = (os.getenv("AX_VL_MODEL") or "qwen-vl-plus").strip()
    mime = _mime_for_image(_ext(name), content_type)
    b64 = base64.b64encode(data).decode("ascii")
    data_url = f"data:{mime};base64,{b64}"
    client = OpenAI(api_key=key, base_url=base)
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "请用中文客观描述这张图片的内容，供聊天助手理解上下文。"
                                "包含主要物体、文字（若有 OCR）、场景与情绪氛围。"
                                "直接输出描述，不要开场白。"
                            ),
                        },
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ],
                }
            ],
            max_tokens=800,
        )
    except Exception as exc:
        obs("attachments", "vl.failed", error=str(exc), model=model, name=name)
        raise AttachmentError(f"图片描述失败：{exc}", status_code=502) from exc

    text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not text:
        raise AttachmentError("图片描述为空，请换一张图再试。", status_code=502)
    return text


def _extract_text(data: bytes) -> tuple[str, bool]:
    try:
        raw = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            raw = data.decode("gb18030")
        except UnicodeDecodeError as exc:
            raise AttachmentError("文本文件不是可识别的 UTF-8/GBK 编码。") from exc
    truncated = len(raw) > TEXT_MAX_CHARS
    if truncated:
        raw = raw[:TEXT_MAX_CHARS]
    text = raw.strip()
    if not text:
        raise AttachmentError("文本文件是空的。")
    return text, truncated


def ingest_bytes(
    data: bytes,
    *,
    filename: str,
    content_type: str = "",
) -> IngestResult:
    if not data:
        raise AttachmentError("空文件。")
    if len(data) > MAX_BYTES:
        raise AttachmentError(f"文件过大（上限 {MAX_BYTES // (1024 * 1024)}MB）。")

    name = (filename or "upload").strip() or "upload"
    kind = _classify(name, content_type)
    if kind == "text":
        text, truncated = _extract_text(data)
        obs("attachments", "ingest.text", name=name, chars=len(text), truncated=truncated)
        return IngestResult(name=name, kind="text", text=text, truncated=truncated)

    caption = _describe_image(data, name=name, content_type=content_type)
    obs("attachments", "ingest.image", name=name, chars=len(caption))
    return IngestResult(name=name, kind="image", text=caption, truncated=False)
