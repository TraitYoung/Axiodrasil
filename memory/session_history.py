"""会话历史统一入口：SQLite 为读权威，Redis 仅写穿加速。"""

from __future__ import annotations

from typing import Dict, List, Optional

from infrastructure.container import get_memory_db


def load_for_prompt(session_id: str, limit: int = 5, *, session_cache=None) -> List[str]:
    """供 LangGraph recent_history：优先 SQLite；空且 Redis 可用时回退。"""
    try:
        lines = get_memory_db().format_chat_history(session_id, limit=limit)
        if lines:
            return lines
    except Exception as e:
        print(f"[session-history] SQLite prompt load failed: {e}")
    if session_cache is None or not getattr(session_cache, "is_available", lambda: False)():
        return []
    try:
        return session_cache.format_recent_history(session_id=session_id, limit=limit)
    except Exception:
        return []


def load_for_ui(session_id: str, limit: int = 50, *, session_cache=None) -> List[Dict[str, str]]:
    """供 history/export API。"""
    try:
        return get_memory_db().get_chat_turns(session_id, limit=limit)
    except Exception as e:
        print(f"[session-history] SQLite UI load failed: {e}")
    if session_cache is None or not getattr(session_cache, "is_available", lambda: False)():
        return []
    try:
        return session_cache.get_recent_turns(session_id=session_id, limit=limit)
    except Exception:
        return []


def append_turn(
    session_id: str,
    user_text: str,
    assistant_text: str,
    *,
    session_cache=None,
) -> None:
    """双写：Redis（可熔断跳过）+ SQLite。"""
    if session_cache is not None:
        try:
            session_cache.append_turn(
                session_id=session_id,
                user_text=user_text,
                assistant_text=assistant_text,
            )
        except Exception:
            pass
    try:
        get_memory_db().append_chat_turn(session_id, user_text, assistant_text)
    except Exception as e:
        print(f"[session-history] SQLite write failed: {e}")


__all__ = ["load_for_prompt", "load_for_ui", "append_turn"]
