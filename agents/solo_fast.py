"""Solo Bina 快速通道：规则估痛感/象限，跳过全量 parser LLM。"""

from __future__ import annotations

from schemas.protocols import TaskIntent

# 急症级（对应 pain_level > 6）
_PAIN_CRITICAL = (
    "心脏狂跳",
    "心慌得",
    "手抖",
    "呼吸困难",
    "喘不上气",
    "濒临昏厥",
    "要晕",
    "昏厥",
    "胸口剧痛",
    "胸口疼得",
    "剧痛",
    "痛得受不了",
    "窒息",
    "抢救",
    "急诊",
    "想死",
    "自杀",
    "自残",
)

_PAIN_MODERATE = (
    "好痛",
    "很痛",
    "疼死",
    "想哭",
    "崩溃",
    "受不了",
    "焦虑发作",
    "恐慌",
    "心慌",
    "胸闷",
)

_Q1_HINTS = (
    "今天必须",
    "今晚必须",
    "截止",
    "ddl",
    "deadline",
    "救命",
    "紧急",
    "来不及了",
)

_Q2_HINTS = (
    "长期",
    "架构",
    "规划",
    "笔记",
    "复盘",
    "路线图",
    "技术方案",
)


def estimate_pain_level(text: str) -> int:
    t = (text or "").strip().lower()
    if not t:
        return 1
    if any(k.lower() in t for k in _PAIN_CRITICAL):
        return 8
    if any(k.lower() in t for k in _PAIN_MODERATE):
        return 5
    return 2


def estimate_quadrant(text: str, *, pain_level: int) -> str:
    if pain_level > 6:
        return "Q1"
    t = (text or "").strip().lower()
    if any(k.lower() in t for k in _Q1_HINTS):
        return "Q1"
    if any(k.lower() in t for k in _Q2_HINTS):
        return "Q2"
    return "Q4"


def synthesize_solo_bina_intent(raw_input: str) -> TaskIntent:
    """合成 Solo 密谈 intent：固定 emotion/bina，痛感与象限用规则。"""
    pain = estimate_pain_level(raw_input)
    quadrant = estimate_quadrant(raw_input, pain_level=pain)
    urgency = 4 if pain > 6 else (3 if pain >= 5 else 1)
    return TaskIntent(
        task_type="emotion",
        persona="bina",
        urgency_level=urgency,
        pain_level=pain,
        raw_input=raw_input,
        quadrant=quadrant,  # type: ignore[arg-type]
    )


__all__ = [
    "estimate_pain_level",
    "estimate_quadrant",
    "synthesize_solo_bina_intent",
]
