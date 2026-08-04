"""服务端 STT：短音频经 DashScope 多模态音频模型转写（支持本地上传，不依赖公网 URL）。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from observability import obs

MAX_BYTES = 8 * 1024 * 1024
AUDIO_EXTS = {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".mpeg", ".mp4"}
AUDIO_MIMES = {
    "audio/webm",
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp3",
    "audio/mp4",
    "audio/m4a",
    "audio/ogg",
    "video/webm",
}


class SttError(ValueError):
    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _ext(name: str, content_type: str) -> str:
    base = (name or "").rsplit("/", 1)[-1]
    if "." in base:
        return "." + base.rsplit(".", 1)[-1].lower()
    ct = (content_type or "").split(";")[0].strip().lower()
    return {
        "audio/webm": ".webm",
        "video/webm": ".webm",
        "audio/wav": ".wav",
        "audio/x-wav": ".wav",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/mp4": ".m4a",
        "audio/m4a": ".m4a",
        "audio/ogg": ".ogg",
    }.get(ct, ".webm")


def transcribe_audio(
    data: bytes,
    *,
    filename: str = "audio.webm",
    content_type: str = "",
) -> str:
    if not data:
        raise SttError("空音频。")
    if len(data) > MAX_BYTES:
        raise SttError(f"音频过大（上限 {MAX_BYTES // (1024 * 1024)}MB）。")

    key = (os.getenv("QWEN_API_KEY") or "").strip()
    if not key:
        raise SttError(
            "服务端语音识别需要 QWEN_API_KEY，请在 .env 配置后重试；也可改用浏览器听写。",
            status_code=503,
        )

    ext = _ext(filename, content_type)
    if ext not in AUDIO_EXTS and (content_type or "").split(";")[0].strip().lower() not in AUDIO_MIMES:
        # 仍允许常见浏览器录音扩展名
        if ext not in {".webm", ".wav", ".mp3", ".ogg", ".m4a"}:
            raise SttError(f"暂不支持该音频类型（{filename or content_type}）。")

    model = (os.getenv("AX_STT_MODEL") or "qwen2-audio-instruct").strip()
    tmp_path: Path | None = None
    try:
        fd, tmp_name = tempfile.mkstemp(suffix=ext or ".webm")
        os.close(fd)
        tmp_path = Path(tmp_name)
        tmp_path.write_bytes(data)

        import dashscope
        from dashscope import MultiModalConversation

        dashscope.api_key = key
        messages = [
            {
                "role": "user",
                "content": [
                    {"audio": f"file://{tmp_path.as_posix()}"},
                    {
                        "text": "请把这段语音转成纯文本。只输出转写结果，不要解释、不加引号。",
                    },
                ],
            }
        ]
        resp = MultiModalConversation.call(model=model, messages=messages)
    except SttError:
        raise
    except Exception as exc:
        obs("stt", "transcribe.failed", error=str(exc), model=model)
        raise SttError(f"语音识别失败：{exc}", status_code=502) from exc
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    status = getattr(resp, "status_code", None)
    if status is not None and int(status) != 200:
        msg = getattr(resp, "message", None) or str(resp)
        obs("stt", "transcribe.api_error", error=msg, model=model, status=status)
        raise SttError(f"语音识别失败：{msg}", status_code=502)

    text = ""
    try:
        output = resp.output
        choices = getattr(output, "choices", None) or []
        if choices:
            content = choices[0].message.content
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and "text" in item:
                        parts.append(str(item["text"]))
                    else:
                        parts.append(str(item))
                text = "".join(parts)
            else:
                text = str(content or "")
        elif isinstance(output, dict):
            text = str(output.get("text") or "")
    except Exception:
        text = str(getattr(resp, "output", "") or "")

    text = (text or "").strip()
    if not text:
        raise SttError("没有听清内容，请再说一次。", status_code=502)
    obs("stt", "transcribe.ok", model=model, chars=len(text))
    return text
