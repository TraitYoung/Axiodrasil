"""角色出图：定妆 LoRA + ComfyUI（邻舍路径的精简移植）。"""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from modules.comfyui.client import ComfyClient, ComfyError
from modules.image_gen.profiles import VisualProfile, load_visual_profile
from modules.image_gen.workflow import build_txt2img_workflow
from observability import obs

_ROOT = Path(__file__).resolve().parents[2]
_OUT_DIR = Path(os.getenv("AX_IMAGE_OUT_DIR") or (_ROOT / "data" / "generated"))

_SELFIE_RE = re.compile(
    r"(自拍|自拍一张|拍一张|发一张|发张照|发张图|发张自拍|"
    r"看看你|看看你长什么样|你的样子|你长什么样|"
    r"照片|相片|selfie|self[\s-]?ie|pic of you|photo of you|send (me )?(a )?(pic|photo|selfie))",
    re.IGNORECASE,
)


class ImageGenError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class GeneratedImage:
    persona_id: str
    file_name: str
    relative_url: str
    local_path: Path
    prompt: str


def image_gen_enabled() -> bool:
    return (os.getenv("AX_IMAGE_GEN_ENABLED") or "1").strip().lower() not in (
        "0",
        "false",
        "off",
        "no",
    )


def detect_selfie_request(text: str) -> bool:
    return bool(_SELFIE_RE.search(text or ""))


def compose_positive(profile: VisualProfile, *, scene: str = "", mode: str = "selfie") -> str:
    parts: list[str] = []
    for lora in profile.loras:
        if lora.trigger_word:
            parts.append(lora.trigger_word)
    if profile.appearance_prompt:
        parts.append(profile.appearance_prompt)
    if mode == "selfie" and profile.selfie_prompt:
        parts.append(profile.selfie_prompt)
    if profile.style_prompt:
        parts.append(profile.style_prompt)
    if scene.strip():
        parts.append(scene.strip())
    # 去重保序
    seen: set[str] = set()
    ordered: list[str] = []
    for p in parts:
        key = p.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(p.strip())
    return ", ".join(ordered)


def generate_persona_image(
    persona_id: str,
    *,
    scene: str = "",
    mode: str = "selfie",
) -> GeneratedImage:
    if not image_gen_enabled():
        raise ImageGenError("图片生成已关闭（AX_IMAGE_GEN_ENABLED=0）。", status_code=503)

    profile = load_visual_profile(persona_id)
    if profile is None or not profile.enabled:
        raise ImageGenError(f"人格 {persona_id} 未配置视觉定妆（config/persona_visual/）。", status_code=404)
    if not profile.loras:
        raise ImageGenError(
            f"{persona_id} 未配置 LoRA。请编辑 config/persona_visual/{persona_id}.json 并放入 ComfyUI/models/loras/。",
            status_code=400,
        )

    positive = compose_positive(profile, scene=scene, mode=mode)
    negative = profile.negative_prompt or "lowres, bad anatomy, watermark"
    workflow = build_txt2img_workflow(
        positive=positive,
        negative=negative,
        loras=profile.loras,
        filename_prefix=f"axiodrasil/{persona_id}",
    )

    client = ComfyClient()
    t0 = time.time()
    try:
        prompt_id = client.queue_prompt(workflow)
        hist = client.wait_history(prompt_id)
        raw, src_name = client.first_output_image(hist)
    except ComfyError as exc:
        obs("image_gen", "comfy.failed", error=str(exc), persona=persona_id)
        raise ImageGenError(str(exc), status_code=exc.status_code) from exc

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(src_name).suffix or ".png"
    file_name = f"{persona_id}-{uuid.uuid4().hex[:12]}{ext}"
    dest = _OUT_DIR / file_name
    dest.write_bytes(raw)

    url = f"/api/v1/images/file/{file_name}"
    obs(
        "image_gen",
        "ok",
        persona=persona_id,
        ms=int((time.time() - t0) * 1000),
        file=file_name,
    )
    return GeneratedImage(
        persona_id=persona_id,
        file_name=file_name,
        relative_url=url,
        local_path=dest,
        prompt=positive,
    )


def maybe_attach_selfie(persona_id: str, user_text: str, reply_text: str) -> str:
    """若用户在要自拍/照片，则出图并拼进 markdown。失败时附加简短说明，不吞原回复。"""
    if not detect_selfie_request(user_text):
        return reply_text
    try:
        img = generate_persona_image(persona_id, mode="selfie")
    except ImageGenError as exc:
        return f"{reply_text}\n\n（想发自拍但出图失败：{exc}）"
    except Exception as exc:  # noqa: BLE001
        return f"{reply_text}\n\n（想发自拍但出图失败：{exc}）"
    return f"{reply_text}\n\n![{persona_id} selfie]({img.relative_url})"
