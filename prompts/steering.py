"""
人格正/负向风格提示（类似 SD 的 positive / negative prompt）。

优先级（高→低）：
1. 环境变量 AX_{PERSONA}_POSITIVE_PROMPT / AX_{PERSONA}_NEGATIVE_PROMPT
2. prompts/steering/{persona}.json
3. 内置默认（目前仅 bina）

拼进 system prompt 末尾，不改写 BIOS 长文人设。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

_STEERING_DIR = Path(__file__).resolve().parent / "steering"

# 内置兜底：Bina 活人感 / 反结构
_DEFAULTS: dict[str, dict[str, str]] = {
    "bina": {
        "positive": (
            "像微信里跟死党随口回；短、碎、有反应；先站队接住情绪；"
            "顺着陛下的话说下去；口语自然（搞定/有点烦/真够呛）。"
        ),
        "negative": (
            "结构化安慰文；拆解对方心理动机；代写下一句台词；"
            "分点列举/小标题/总结陈词；固定晚饭热汤收尾；"
            "客服尾句与鸡汤；没被问「怎么办」却给方案。"
        ),
    },
}


def _env_key(persona: str, kind: str) -> str:
    return f"AX_{persona.strip().upper()}_{kind.strip().upper()}_PROMPT"


@lru_cache(maxsize=32)
def _load_file(persona: str) -> dict[str, str]:
    path = _STEERING_DIR / f"{persona}.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for k in ("positive", "negative"):
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
        elif isinstance(v, list):
            joined = "；".join(str(x).strip() for x in v if str(x).strip())
            if joined:
                out[k] = joined
    return out


def get_steering(persona: str) -> tuple[str, str]:
    """返回 (positive, negative)，缺省为空串。"""
    pid = (persona or "").strip().lower()
    if not pid:
        return "", ""

    file_cfg = _load_file(pid)
    defaults = _DEFAULTS.get(pid, {})

    positive = (
        (os.getenv(_env_key(pid, "positive")) or "").strip()
        or file_cfg.get("positive", "")
        or defaults.get("positive", "")
    )
    negative = (
        (os.getenv(_env_key(pid, "negative")) or "").strip()
        or file_cfg.get("negative", "")
        or defaults.get("negative", "")
    )
    return positive, negative


def format_steering_block(positive: str, negative: str) -> str:
    parts: list[str] = []
    if positive:
        parts.append(f"【正向风格提示】请尽量体现：\n{positive}")
    if negative:
        parts.append(f"【负向风格提示】请坚决避免：\n{negative}")
    return "\n\n".join(parts)


def with_style_steering(system_prompt: str, persona: str) -> str:
    """把正/负向风格提示拼进 system prompt。"""
    block = format_steering_block(*get_steering(persona))
    if not block:
        return system_prompt
    return f"{system_prompt}\n\n{block}"


def clear_steering_cache() -> None:
    """测试或热改 json 后可清缓存。"""
    _load_file.cache_clear()


__all__ = [
    "get_steering",
    "format_steering_block",
    "with_style_steering",
    "clear_steering_cache",
]
