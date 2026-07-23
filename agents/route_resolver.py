"""
路由决策逻辑：从 router.py 抽出，供 tracing 等模块直接导入，消除循环依赖。

真正的路由决策在 `_resolve_route` 里一次性算好 (persona, route_key)，
`route_by_intent` 只做确定性查表。
"""

from __future__ import annotations

import os
import random
import re
from datetime import datetime
from typing import Optional

from agents.persona_meta import (
    CLEANING_KEYWORDS,
    CONFLICT_KEYWORDS,
    CONTINUED_WORK_KEYWORDS,
    DOMAIN_DEFAULT_PERSONA,
    FATIGUE_KEYWORDS,
    INDULGENCE_KEYWORDS,
    PERSONA_TO_ROUTE,
    ROUTE_TO_NODE,
    SUMMON_ALIASES,
    ART_KEYWORDS,
    BOMING_KEYWORDS,
    MATH_KEYWORDS,
    POLITICS_KEYWORDS,
    SHOPPING_KEYWORDS,
    TAKI_KEYWORDS,
)
from schemas.protocols import TaskIntent

_SUMMON_PATTERN = re.compile(r"传\s*([A-Za-z\u4e00-\u9fa5]{1,6})")

_DIVERSITY_PATCH_ENABLED = os.getenv("AX_DIVERSITY_PATCH_ENABLED", "1").strip() not in ("0", "false", "off")
_DIVERSITY_PATCH_PROB = float(os.getenv("AX_DIVERSITY_PATCH_PROB", "0.15"))
_DIVERSITY_CANDIDATES = ["tianji", "qianjin", "vinci"]


def match_summon(text: str) -> Optional[str]:
    """召唤协议：「传 [Name]」，优先级高于一切触发逻辑（BIOS Module 2.1），
    但不能绕过 pain_level > 6 的医疗安全熔断（在 resolve_route 里排在更前面）。"""
    m = _SUMMON_PATTERN.search(text)
    if not m:
        return None
    token = m.group(1).strip()
    return SUMMON_ALIASES.get(token) or SUMMON_ALIASES.get(token.lower())


def _is_late_night(now: datetime) -> bool:
    """BIOS ACT_II 软红线触发时段：23:30 之后，到次日 6 点前都算"仍在熬"。"""
    if now.hour == 23 and now.minute >= 30:
        return True
    return 0 <= now.hour < 6


def _detect_debate(text: str) -> bool:
    """BIOS Module 2.1 冲突规则：只有当"逻辑"与"直觉"冲突时，才允许 Bit 和
    Bina 同时发言辩论。"""
    return any(k in text for k in INDULGENCE_KEYWORDS) and any(k in text for k in CONFLICT_KEYWORDS)


def _maybe_diversity_patch(intent: TaskIntent) -> Optional[str]:
    """BIOS Module 5.7 多样性补丁。只允许在 resolve_route 里被调用恰好一次。"""
    if not _DIVERSITY_PATCH_ENABLED:
        return None
    if intent.quadrant not in ("Q3", "Q4"):
        return None
    if random.random() >= _DIVERSITY_PATCH_PROB:
        return None
    return random.choice(_DIVERSITY_CANDIDATES)


def resolve_route(
    intent: TaskIntent,
    current_input: str,
    now: datetime,
    *,
    forced_persona: Optional[str] = None,
) -> tuple[str, str]:
    """一次性算出 (persona, route_key)。只应该在 node_parser 里被调用一次。

    forced_persona：酒馆 Group Chat 指定说话人；仍不能绕过 pain_level > 6 医疗熔断。
    """
    lower_input = current_input.lower()

    # 0. 安全底线：医疗硬熔断
    if intent.pain_level > 6:
        return "bina", "emotion_route"

    # 0.5 酒馆强制人设（跳过关键词/多样性/辩论并行）
    if forced_persona:
        persona = SUMMON_ALIASES.get(forced_persona) or SUMMON_ALIASES.get(
            forced_persona.lower()
        )
        if persona and persona in PERSONA_TO_ROUTE:
            return persona, PERSONA_TO_ROUTE[persona]

    # 1. 召唤协议
    summon_persona = match_summon(current_input)
    if summon_persona:
        return summon_persona, PERSONA_TO_ROUTE[summon_persona]

    # 2. 清洗流水线优先
    if any(k in lower_input for k in CLEANING_KEYWORDS):
        return "bit", "bit_route"

    # 3. 冲突辩论
    if _detect_debate(current_input):
        return "bina", "debate_route"

    # 4. Fukucho 深夜软红线
    if _is_late_night(now) and any(k in current_input for k in CONTINUED_WORK_KEYWORDS):
        return "fukucho", "fukucho_route"

    # 5. Qianjin 非急症疲惫问诊
    if any(k in current_input for k in FATIGUE_KEYWORDS):
        return "qianjin", "qianjin_route"

    # 6. Tianji 购物/防骗/八卦
    if any(k in current_input for k in SHOPPING_KEYWORDS):
        return "tianji", "tianji_route"

    # 7. Vinci 艺术/设计
    if any(k in current_input for k in ART_KEYWORDS):
        return "vinci", "vinci_route"

    # 8. bit domain 内的精细化
    if intent.task_type == "bit":
        if any(k in current_input for k in MATH_KEYWORDS):
            return "planck", "planck_route"
        if any(k in current_input for k in TAKI_KEYWORDS):
            return "taki", "taki_route"
        return "bit", "bit_route"

    # 9. juzheng domain 内的精细化
    if intent.task_type == "juzheng":
        if any(k in current_input for k in POLITICS_KEYWORDS):
            return "jiafa", "jiafa_route"
        if any(k in current_input for k in BOMING_KEYWORDS):
            return "boming", "boming_route"
        return "chizheng", "juzheng_route"

    # 10. jean domain
    if intent.task_type == "jean":
        return "jean", "jean_route"

    # 11. emotion domain 默认分支
    if intent.task_type == "emotion":
        diversity_persona = _maybe_diversity_patch(intent)
        if diversity_persona:
            return diversity_persona, PERSONA_TO_ROUTE[diversity_persona]
        return "bina", "emotion_route"

    # unknown 兜底
    return "chizheng", "juzheng_route"


def route_by_intent(state: dict) -> str:
    """条件边使用的路由函数。只做确定性查表，不触发随机逻辑。"""
    resolved = state.get("resolved_route_key")
    if resolved:
        return resolved
    intent = state.get("intent")
    persona = getattr(intent, "persona", None) if intent is not None else None
    return PERSONA_TO_ROUTE.get(persona or "chizheng", "juzheng_route")


__all__ = [
    "resolve_route",
    "route_by_intent",
    "match_summon",
    "ROUTE_TO_NODE",
]
