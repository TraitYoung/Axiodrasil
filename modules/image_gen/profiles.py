"""人格视觉定妆配置（LoRA + 外貌底词）。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[2]
_DIR = _ROOT / "config" / "persona_visual"


@dataclass
class LoraSpec:
    path: str
    weight: float = 0.8
    trigger_word: str = ""


@dataclass
class VisualProfile:
    persona_id: str
    display_name: str = ""
    enabled: bool = True
    loras: list[LoraSpec] = field(default_factory=list)
    appearance_prompt: str = ""
    negative_prompt: str = ""
    style_prompt: str = ""
    selfie_prompt: str = ""
    # 人读设定（SSOT 正文）；出图仍用 appearance_prompt 等字段
    canon: dict[str, Any] = field(default_factory=dict)
    notes: str = ""


def load_visual_profile(persona_id: str) -> VisualProfile | None:
    pid = (persona_id or "").strip().lower()
    if not pid:
        return None
    path = _DIR / f"{pid}.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    loras: list[LoraSpec] = []
    for item in data.get("loras") or []:
        if not isinstance(item, dict):
            continue
        p = str(item.get("path") or "").strip()
        if not p:
            continue
        loras.append(
            LoraSpec(
                path=p,
                weight=float(item.get("weight") or 0.8),
                trigger_word=str(item.get("trigger_word") or item.get("triggerWord") or "").strip(),
            )
        )

    # 环境变量可覆盖单个 LoRA（便于本机调试）
    env_lora = (os.getenv(f"AX_{pid.upper()}_LORA") or "").strip()
    if env_lora:
        w = float(os.getenv(f"AX_{pid.upper()}_LORA_WEIGHT") or "0.85")
        tw = (os.getenv(f"AX_{pid.upper()}_LORA_TRIGGER") or "").strip()
        loras = [LoraSpec(path=env_lora, weight=w, trigger_word=tw)] + [
            x for x in loras if x.path != env_lora
        ]

    canon_raw = data.get("canon")
    canon = dict(canon_raw) if isinstance(canon_raw, dict) else {}

    return VisualProfile(
        persona_id=str(data.get("persona_id") or pid),
        display_name=str(data.get("display_name") or pid),
        enabled=bool(data.get("enabled", True)),
        loras=loras,
        appearance_prompt=str(data.get("appearance_prompt") or "").strip(),
        negative_prompt=str(data.get("negative_prompt") or "").strip(),
        style_prompt=str(data.get("style_prompt") or "").strip(),
        selfie_prompt=str(data.get("selfie_prompt") or "").strip(),
        canon=canon,
        notes=str(data.get("notes") or "").strip(),
    )


def profile_to_public(profile: VisualProfile) -> dict[str, Any]:
    return {
        "persona_id": profile.persona_id,
        "display_name": profile.display_name,
        "enabled": profile.enabled,
        "ssot": "config/persona_visual/{}.json".format(profile.persona_id),
        "canon": profile.canon,
        "loras": [
            {"path": x.path, "weight": x.weight, "trigger_word": x.trigger_word}
            for x in profile.loras
        ],
        "has_appearance": bool(profile.appearance_prompt),
        "notes": profile.notes,
    }
