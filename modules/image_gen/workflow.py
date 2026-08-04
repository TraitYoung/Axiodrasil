"""构建 ComfyUI API 工作流：Checkpoint + 可选多层 LoraLoader（邻舍式定妆）。"""

from __future__ import annotations

import os
import random
from typing import Any

from modules.image_gen.profiles import LoraSpec


def _ckpt_name() -> str:
    return (
        os.getenv("AX_COMFYUI_CKPT")
        or os.getenv("AX_COMFYUI_CHECKPOINT")
        or "sd_xl_base_1.0.safetensors"
    ).strip()


def build_txt2img_workflow(
    *,
    positive: str,
    negative: str,
    loras: list[LoraSpec] | None = None,
    width: int = 832,
    height: int = 1216,
    steps: int | None = None,
    cfg: float | None = None,
    seed: int | None = None,
    filename_prefix: str = "axiodrasil/bina",
) -> dict[str, Any]:
    """
    标准 SDXL 系 API 图：
      CheckpointLoaderSimple → (LoraLoader*) → CLIPTextEncode ×2 → KSampler → VAEDecode → SaveImage
    LoRA 文件名相对于 ComfyUI/models/loras/。
    """
    w = int(os.getenv("AX_COMFYUI_WIDTH") or width)
    h = int(os.getenv("AX_COMFYUI_HEIGHT") or height)
    steps = int(os.getenv("AX_COMFYUI_STEPS") or steps or 24)
    cfg = float(os.getenv("AX_COMFYUI_CFG") or cfg or 6.5)
    seed = int(seed if seed is not None else random.randint(1, 2**31 - 1))
    sampler = (os.getenv("AX_COMFYUI_SAMPLER") or "euler").strip()
    scheduler = (os.getenv("AX_COMFYUI_SCHEDULER") or "normal").strip()

    nodes: dict[str, Any] = {
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": _ckpt_name()},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {"width": w, "height": h, "batch_size": 1},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": filename_prefix, "images": ["8", 0]},
        },
    }

    model_ref: list[Any] = ["4", 0]
    clip_ref: list[Any] = ["4", 1]
    next_id = 20
    for lora in loras or []:
        if not lora.path:
            continue
        nid = str(next_id)
        next_id += 1
        nodes[nid] = {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": lora.path,
                "strength_model": float(lora.weight),
                "strength_clip": float(lora.weight),
                "model": model_ref,
                "clip": clip_ref,
            },
        }
        model_ref = [nid, 0]
        clip_ref = [nid, 1]

    nodes["6"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": positive, "clip": clip_ref},
    }
    nodes["7"] = {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": negative, "clip": clip_ref},
    }
    nodes["3"] = {
        "class_type": "KSampler",
        "inputs": {
            "seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": sampler,
            "scheduler": scheduler,
            "denoise": 1.0,
            "model": model_ref,
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    }
    return nodes
