"""
记忆上下文拼装：把 L2 摘要 / 碎片 / 短历史 / 内阁三层格式化成可注入 prompt 的文本块。

读写解耦：database 只负责存取；本模块负责预算内截断与措辞，供 parser / 人格节点共用。
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from config.context_budget import (
    MAX_AGENT_HISTORY_CHARS,
    MAX_AGENT_HISTORY_TURNS,
    MAX_CONSENSUS_INJECT_CHARS,
    MAX_DEBATE_BUFFER_TURNS,
    MAX_DEBATE_INJECT_CHARS,
    MAX_FRAGMENT_INJECT_CHARS,
    MAX_PERSONA_PRIVATE_CHARS,
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
    persona: Optional[str] = None,
    shared_only: bool = False,
) -> str:
    """偏好/事实碎片召回；默认不注入 emotion 快照。"""
    rows = memory_db.get_fragments(
        thread_id,
        fragment_type=None,
        limit=limit * 2,
        persona=persona,
        shared_only=shared_only,
    )
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
    if MAX_AGENT_HISTORY_TURNS > 0 and len(lines) > MAX_AGENT_HISTORY_TURNS:
        lines = lines[-MAX_AGENT_HISTORY_TURNS:]
    trimmed = truncate_history_lines(lines)
    joined = "\n".join(
        clip_text(line, MAX_SINGLE_HISTORY_LINE_CHARS) for line in trimmed
    )
    joined = clip_text(joined, MAX_AGENT_HISTORY_CHARS)
    if not joined.strip():
        return ""
    return f"【最近对话】（短上下文，用于接上指代）：\n{joined}"


def format_consensus_block(memory_db: PersonaMemory, thread_id: str, limit: int = 3) -> str:
    """M3 共识层注入。"""
    rows = memory_db.get_recent_consensus(thread_id, limit=limit)
    if not rows:
        return ""
    chunks: List[str] = []
    for i, row in enumerate(reversed(rows), start=1):
        parts: List[str] = []
        summary = (row.get("summary") or "").strip()
        if summary:
            parts.append(summary)
        for label, key in (
            ("结论", "conclusions"),
            ("未决", "unresolved"),
            ("行动", "action_items"),
        ):
            val = (row.get(key) or "").strip()
            if val:
                parts.append(f"{label}：\n{val}")
        if parts:
            chunks.append(f"[共识 {i}]\n" + "\n".join(parts))
    if not chunks:
        return ""
    body = clip_text("\n\n".join(chunks), MAX_CONSENSUS_INJECT_CHARS)
    return f"【内阁共识层】（全员共享的已拍板事实与承诺，勿推翻已决，可引用）：\n{body}"


def format_persona_private_block(
    memory_db: PersonaMemory, thread_id: str, persona: str, limit: int = 10
) -> str:
    """M2 人设私忆：仅当前说话人。"""
    if not persona:
        return ""
    rows = memory_db.get_fragments(
        thread_id, fragment_type=None, limit=limit * 2, persona=persona
    )
    if not rows:
        return ""
    lines: List[str] = []
    for row in rows:
        text = (row.get("content") or "").strip()
        if not text:
            continue
        lines.append(f"- {text}")
        if len(lines) >= limit:
            break
    if not lines:
        return ""
    body = clip_text("\n".join(lines), MAX_PERSONA_PRIVATE_CHARS)
    return (
        f"【你的私忆｜{persona}】（仅你可见，可影响立场；不要向同僚逐字宣读）：\n{body}"
    )


def format_debate_block(memory_db: PersonaMemory, thread_id: str) -> str:
    """M1 吵架层：仅当 status=open 时注入。"""
    if memory_db.get_debate_status(thread_id) != "open":
        return ""
    turns = memory_db.get_debate_turns(thread_id, limit=MAX_DEBATE_BUFFER_TURNS)
    if not turns:
        return ""
    lines: List[str] = []
    for t in turns:
        content = (t.get("content") or "").strip()
        if not content:
            continue
        speaker = t.get("speaker") or "?"
        role = t.get("role") or ""
        if role == "user":
            lines.append(f"[陛下]: {content}")
        else:
            lines.append(f"[{speaker}]: {content}")
    if not lines:
        return ""
    body = clip_text("\n".join(lines), MAX_DEBATE_INJECT_CHARS)
    return (
        "【内阁吵架层】（进行中的争执，全员共享；可反驳同僚，只以本人身份发言）：\n"
        f"{body}"
    )


def compose_cabinet_context(
    memory_db: PersonaMemory,
    thread_id: str,
    persona: str,
) -> str:
    """固定顺序：M3 → M2 → M1。"""
    parts: List[str] = []
    try:
        c = format_consensus_block(memory_db, thread_id)
        if c:
            parts.append(c)
    except Exception as e:
        print(f"⚠️ [memory] 共识注入失败: {e}")
    try:
        p = format_persona_private_block(memory_db, thread_id, persona)
        if p:
            parts.append(p)
    except Exception as e:
        print(f"⚠️ [memory] 私忆注入失败: {e}")
    try:
        d = format_debate_block(memory_db, thread_id)
        if d:
            parts.append(d)
    except Exception as e:
        print(f"⚠️ [memory] 吵架层注入失败: {e}")
    return "\n\n".join(parts)


def compose_user_message(
    base_user_status: str,
    *,
    recent_history: Optional[Iterable[str]] = None,
    summary_block: str = "",
    fragment_block: str = "",
    cabinet_block: str = "",
) -> str:
    """人格 HumanMessage：内阁三层 / 摘要 / 碎片 / 短历史在前，本轮用户状态在后。"""
    parts: List[str] = []
    if cabinet_block.strip():
        parts.append(cabinet_block.strip())
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
    "compose_cabinet_context",
    "compose_user_message",
    "format_agent_history_block",
    "format_consensus_block",
    "format_debate_block",
    "format_fragments_block",
    "format_persona_private_block",
    "format_summaries_block",
]
