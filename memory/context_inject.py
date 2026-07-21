"""
记忆上下文拼装：把 L2 摘要 / 碎片 / 短历史格式化成可注入 prompt 的文本块。

读写解耦：database 只负责存取；本模块负责预算内截断与措辞，供 parser / 人格节点共用。
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from config.context_budget import (
    MAX_AGENT_HISTORY_CHARS,
    MAX_AGENT_HISTORY_TURNS,
    MAX_FRAGMENT_INJECT_CHARS,
    MAX_SINGLE_HISTORY_LINE_CHARS,
    MAX_SUMMARY_INJECT_CHARS,
    clip_text,
    truncate_history_lines,
)
from memory.database import PersonaMemory


def format_summaries_block(memory_db: PersonaMemory, thread_id: str, limit: int = 3) -> str:
    """最近若干条 L2 摘要，旧→新，整体截断。"""
    rows = memory_db.get_recent_summaries(thread_id, limit=limit)
    if not rows:
        return ""
    # get_recent_summaries 是新→旧，拼进 prompt 时改回旧→新更自然
    lines: List[str] = []
    for i, row in enumerate(reversed(rows), start=1):
        text = (row.get("summary") or "").strip()
        if not text:
            continue
        lines.append(f"[摘要 {i}] {text}")
    if not lines:
        return ""
    body = clip_text("\n".join(lines), MAX_SUMMARY_INJECT_CHARS)
    return f"【中期会话摘要】（跨窗口记忆，供指代与续聊，勿逐字复述）：\n{body}"


def format_fragments_block(
    memory_db: PersonaMemory,
    thread_id: str,
    *,
    fragment_types: Optional[Sequence[str]] = ("preference", "fact"),
    limit: int = 12,
) -> str:
    """偏好/事实碎片召回；默认不注入 emotion 快照，避免把旧情绪当硬事实。"""
    rows = memory_db.get_fragments(thread_id, fragment_type=None, limit=limit * 2)
    if not rows:
        return ""
    allowed = set(fragment_types) if fragment_types else None
    lines: List[str] = []
    for row in rows:
        ftype = str(row.get("fragment_type") or "")
        if allowed is not None and ftype not in allowed:
            continue
        text = (row.get("content") or "").strip()
        if not text:
            continue
        label = {"preference": "偏好", "fact": "事实", "emotion": "情绪"}.get(ftype, ftype)
        lines.append(f"- ({label}) {text}")
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    body = clip_text("\n".join(lines), MAX_FRAGMENT_INJECT_CHARS)
    return f"【已知偏好与事实】（来自长期记忆碎片，可自然引用，勿清单式复读）：\n{body}"


def format_agent_history_block(recent_history: Iterable[str]) -> str:
    """人格节点侧短历史：与 parser 同源列表，但用更紧的字符预算。"""
    lines = list(recent_history) if recent_history else []
    if not lines:
        return ""
    # 只保留最近 N 轮（列表旧→新）
    if MAX_AGENT_HISTORY_TURNS > 0 and len(lines) > MAX_AGENT_HISTORY_TURNS:
        lines = lines[-MAX_AGENT_HISTORY_TURNS:]
    trimmed = truncate_history_lines(lines)
    # truncate_history_lines 用的是 parser 总预算；再按 agent 预算裁一次
    joined = "\n".join(
        clip_text(line, MAX_SINGLE_HISTORY_LINE_CHARS) for line in trimmed
    )
    joined = clip_text(joined, MAX_AGENT_HISTORY_CHARS)
    if not joined.strip():
        return ""
    return f"【最近对话】（短上下文，用于接上指代）：\n{joined}"


def compose_user_message(
    base_user_status: str,
    *,
    recent_history: Optional[Iterable[str]] = None,
    summary_block: str = "",
    fragment_block: str = "",
) -> str:
    """人格 HumanMessage：摘要/碎片/短历史在前，本轮用户状态在后。"""
    parts: List[str] = []
    if summary_block.strip():
        parts.append(summary_block.strip())
    if fragment_block.strip():
        parts.append(fragment_block.strip())
    history_block = format_agent_history_block(recent_history or [])
    if history_block:
        parts.append(history_block)
    parts.append(base_user_status.strip())
    return "\n\n".join(p for p in parts if p)


__all__ = [
    "compose_user_message",
    "format_agent_history_block",
    "format_fragments_block",
    "format_summaries_block",
]
