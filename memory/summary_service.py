"""
滚动摘要触发服务：从 main.py 下沉至此，便于非 HTTP 上下文也能调用。

每隔 N 轮对话触发一次滚动摘要生成（异步，不阻塞响应）。
"""

from __future__ import annotations

from infrastructure.container import get_summary_every_n_turns
from memory import async_tasks, enrichment
from memory.database import PersonaMemory


def maybe_trigger_rolling_summary(session_id: str, session_cache, memory_db: PersonaMemory) -> None:
    """每轮对话结束后调用一次：累计计数，达到阈值就异步生成一段中期摘要。

    摘要素材优先取 Redis 热窗；若 Redis 空/不可用则回退到 SQLite chat_turns。
    """
    try:
        n_turns = get_summary_every_n_turns()
        turns_since_summary = memory_db.bump_turn_counter(session_id)
        if turns_since_summary >= n_turns:
            recent_turns = []
            try:
                recent_turns = session_cache.get_recent_turns(session_id, limit=n_turns)
            except Exception:
                recent_turns = []
            if not recent_turns:
                recent_turns = memory_db.get_chat_turns(session_id, limit=n_turns)
            if recent_turns:
                async_tasks.schedule(
                    enrichment.generate_rolling_summary,
                    thread_id=session_id,
                    turns=recent_turns,
                    db_path=memory_db.db_path,
                )
    except Exception as e:
        print(f"[rolling-summary] counter/schedule failed: {e}")


__all__ = ["maybe_trigger_rolling_summary"]
