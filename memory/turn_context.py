"""回合级记忆预取：本对话 L2 + 共享记忆池 fragments/cabinet。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from infrastructure.container import get_memory_db
from memory.context_inject import (
    compose_cabinet_context,
    format_fragments_block,
    format_summaries_block,
)


@dataclass
class TurnContext:
    """conversation_id：L2 摘要；memory_thread_id：Mood/L3/碎片/内阁。"""

    conversation_id: str
    memory_thread_id: str
    recent_history: List[str] = field(default_factory=list)
    summary_block: str = ""
    fragment_block: str = ""
    cabinet_block: str = ""
    fragments_loaded: bool = False
    cabinet_loaded_for: str = ""

    @property
    def thread_id(self) -> str:
        """兼容旧调用：摘要线程 = 对话 id。"""
        return self.conversation_id

    def ensure_fragments(self) -> str:
        if self.fragments_loaded:
            return self.fragment_block
        try:
            self.fragment_block = format_fragments_block(
                get_memory_db(), self.memory_thread_id, shared_only=True
            )
        except Exception as e:
            print(f"[memory] fragment prefetch failed: {e}")
            self.fragment_block = ""
        self.fragments_loaded = True
        return self.fragment_block

    def ensure_cabinet(self, persona: str = "") -> str:
        key = persona or ""
        if self.cabinet_loaded_for == key:
            return self.cabinet_block
        try:
            self.cabinet_block = compose_cabinet_context(
                get_memory_db(), self.memory_thread_id, persona
            )
        except Exception as e:
            print(f"[memory] cabinet prefetch failed: {e}")
            self.cabinet_block = ""
        self.cabinet_loaded_for = key
        return self.cabinet_block


def build_turn_context(
    conversation_id: str,
    recent_history: Optional[List[str]] = None,
    *,
    memory_thread_id: Optional[str] = None,
    prefetch_summary: bool = True,
) -> TurnContext:
    mem = (memory_thread_id or conversation_id).strip() or conversation_id
    ctx = TurnContext(
        conversation_id=conversation_id,
        memory_thread_id=mem,
        recent_history=list(recent_history or []),
    )
    if prefetch_summary:
        try:
            # L2 挂在对话上，避免多谈话摘要串味
            ctx.summary_block = format_summaries_block(get_memory_db(), conversation_id)
        except Exception as e:
            print(f"[memory] summary prefetch failed: {e}")
            ctx.summary_block = ""
    return ctx


__all__ = ["TurnContext", "build_turn_context"]
