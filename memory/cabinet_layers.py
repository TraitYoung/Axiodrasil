"""
内阁三层记忆语义层：M1 吵架 / M2 人设私忆 / M3 共识。

存储落在 PersonaMemory（SQLite）；本模块负责开闭吵、写回、压缩与触发口令。
"""

from __future__ import annotations

import re
from typing import List, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from config.context_budget import MAX_DEBATE_BUFFER_TURNS
from infrastructure.container import get_db_path, get_enrichment_llm, get_memory_db
from schemas.memory import ConsensusExtraction, PersonaPrivateExtraction

# 显式散会口令（用户或发言文本命中即触发压缩）
CONSENSUS_CLOSE_PATTERNS = (
    "散会",
    "达成共识",
    "先这样",
    "记下结论",
)

_AX_PERSONA_RE = re.compile(r"\[AX_PERSONA:([a-zA-Z]+)\]", re.IGNORECASE)


def detect_consensus_close(text: str) -> bool:
    if not text:
        return False
    return any(p in text for p in CONSENSUS_CLOSE_PATTERNS)


def is_debate_open(thread_id: str) -> bool:
    return get_memory_db().get_debate_status(thread_id) == "open"


def ensure_debate_open(thread_id: str) -> None:
    if not is_debate_open(thread_id):
        get_memory_db().open_debate(thread_id)


def append_debate_exchange(
    thread_id: str,
    *,
    user_text: str,
    assistant_text: str,
    persona: str,
) -> None:
    """群聊一轮：用户句 + 当前人设回复写入 M1（自动开吵）。"""
    db = get_memory_db()
    ensure_debate_open(thread_id)
    if user_text and user_text.strip():
        db.append_debate_turn(thread_id, "user", "user", user_text.strip())
    if assistant_text and assistant_text.strip():
        db.append_debate_turn(
            thread_id, persona or "unknown", "assistant", assistant_text.strip()
        )


def close_and_compress(thread_id: str) -> Optional[str]:
    """压缩 M1 → M3，清空吵架缓冲并关闭。返回写入的摘要文本；无缓冲则只关吵。"""
    db = get_memory_db()
    turns = db.get_debate_turns(thread_id, limit=MAX_DEBATE_BUFFER_TURNS)
    if not turns:
        db.close_debate(thread_id)
        return None

    lines: List[str] = []
    for t in turns:
        speaker = t.get("speaker") or "?"
        role = t.get("role") or ""
        content = (t.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            lines.append(f"[陛下]: {content}")
        else:
            lines.append(f"[{speaker}]: {content}")
    transcript = "\n".join(lines)

    summary_text = ""
    conclusions = ""
    unresolved = ""
    action_items = ""

    llm = get_enrichment_llm()
    if llm is not None:
        try:
            structured = llm.with_structured_output(ConsensusExtraction)
            result: ConsensusExtraction = structured.invoke(
                [
                    SystemMessage(
                        content=(
                            "你是内阁书记官。把下面的内阁争执记录压缩为共识："
                            "conclusions=已拍板；unresolved=仍分歧；action_items=共同行动；"
                            "summary=一两句总述。不要编造未出现的事实。"
                        )
                    ),
                    HumanMessage(content=transcript),
                ]
            )
            summary_text = (result.summary or "").strip()
            conclusions = "\n".join(f"- {x}" for x in result.conclusions if x.strip())
            unresolved = "\n".join(f"- {x}" for x in result.unresolved if x.strip())
            action_items = "\n".join(f"- {x}" for x in result.action_items if x.strip())
            if not summary_text:
                parts = []
                if result.conclusions:
                    parts.append("结论：" + "；".join(result.conclusions[:3]))
                if result.action_items:
                    parts.append("行动：" + "；".join(result.action_items[:3]))
                summary_text = " ".join(parts) or "内阁已散会，本轮争执已归档。"
        except Exception as e:
            print(f"[cabinet] compress failed, truncate fallback: {e}")
            summary_text = transcript[:800]

    if not summary_text:
        summary_text = transcript[:800]

    db.save_consensus(
        thread_id=thread_id,
        summary=summary_text,
        conclusions=conclusions,
        unresolved=unresolved,
        action_items=action_items,
        source_turn_count=len(turns),
    )
    db.clear_debate_turns(thread_id)
    db.close_debate(thread_id)
    return summary_text


def extract_persona_private(
    thread_id: str,
    persona: str,
    *,
    user_text: str,
    assistant_text: str,
    db_path: Optional[str] = None,
) -> None:
    """异步：从本轮人设发言提炼 M2 私忆。"""
    if not persona:
        return
    llm = get_enrichment_llm()
    if llm is None:
        return
    path = db_path or get_db_path()
    from memory.database import PersonaMemory

    memory_db = PersonaMemory(db_path=path)
    try:
        structured = llm.with_structured_output(PersonaPrivateExtraction)
        result: PersonaPrivateExtraction = structured.invoke(
            [
                SystemMessage(
                    content=(
                        f"你在归档内阁人格「{persona}」的私有笔记。"
                        "只提取该人设本人的立场/偏见/对陛下的私交印象，不要写公开共识。"
                        "没有值得私记的内容就返回空列表。"
                    )
                ),
                HumanMessage(
                    content=f"陛下：{user_text}\n[{persona}]：{assistant_text}"
                ),
            ]
        )
    except Exception as e:
        print(f"[cabinet] 人设私忆提取失败: {e}")
        return

    for note in result.private_notes:
        text = (note or "").strip()
        if not text:
            continue
        try:
            memory_db.save_fragment(
                thread_id=thread_id,
                content=text,
                fragment_type="preference",
                persona=persona,
            )
        except Exception as e:
            print(f"[cabinet] 私忆落库失败: {e}")


__all__ = [
    "CONSENSUS_CLOSE_PATTERNS",
    "append_debate_exchange",
    "close_and_compress",
    "detect_consensus_close",
    "ensure_debate_open",
    "extract_persona_private",
    "is_debate_open",
]
