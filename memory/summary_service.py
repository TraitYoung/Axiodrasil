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

    摘要内容来自 Redis 最近 N 轮热缓存，不阻塞当前请求的响应。
    """
    try:
        n_turns = get_summary_every_n_turns()
        turns_since_summary = memory_db.bump_turn_counter(session_id)
        if turns_since_summary >= n_turns:
            recent_turns = session_cache.get_recent_turns(session_id, limit=n_turns)
            if recent_turns:
                async_tasks.schedule(
                    enrichment.generate_rolling_summary,
                    thread_id=session_id,
                    turns=recent_turns,
                )
    except Exception as e:
        print(f"⚠️ [rolling-summary] 计数/调度失败（不影响主流程）: {e}")


__all__ = ["maybe_trigger_rolling_summary"]
