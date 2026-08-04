import json
import os
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import redis


class SessionCache:
    """基于 Redis 的会话热缓存，用于滑动窗口上下文注入。"""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        ttl_seconds: int = 3600,
        window_size: int = 5,
        *,
        circuit_cooldown_sec: float = 30.0,
    ) -> None:
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.ttl_seconds = ttl_seconds
        self.window_size = window_size
        self._circuit_cooldown_sec = circuit_cooldown_sec
        self._down_until = 0.0
        # 短超时：Redis 未开时尽快失败，避免 health / 热缓存拖死请求
        self.client = redis.Redis.from_url(
            self.redis_url,
            decode_responses=True,
            socket_connect_timeout=0.4,
            socket_timeout=0.8,
        )

    def _mark_down(self) -> None:
        self._down_until = time.monotonic() + self._circuit_cooldown_sec

    def is_available(self) -> bool:
        """进程内熔断：近期失败则跳过 Redis，避免每轮 +0.8s。"""
        return time.monotonic() >= self._down_until

    def ping(self) -> bool:
        if not self.is_available():
            return False
        try:
            ok = bool(self.client.ping())
            if not ok:
                self._mark_down()
            return ok
        except Exception:
            self._mark_down()
            return False

    def _key(self, session_id: str) -> str:
        return f"session:{session_id}:chat_turns"

    def append_turn(self, session_id: str, user_text: str, assistant_text: str) -> None:
        if not self.is_available():
            return
        payload = {
            "user": user_text,
            "assistant": assistant_text,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        key = self._key(session_id)
        serialized = json.dumps(payload, ensure_ascii=False)
        try:
            self.client.lpush(key, serialized)
            self.client.ltrim(key, 0, self.window_size - 1)
            self.client.expire(key, self.ttl_seconds)
        except Exception:
            self._mark_down()

    def get_recent_turns(self, session_id: str, limit: int = 5) -> List[Dict[str, str]]:
        if not self.is_available():
            return []
        key = self._key(session_id)
        try:
            raw_items = self.client.lrange(key, 0, max(limit, 1) - 1)
        except Exception:
            self._mark_down()
            return []
        turns: List[Dict[str, str]] = []

        # Redis 列表是新到旧，返回时反转为旧到新，便于 prompt 拼接
        for item in reversed(raw_items):
            try:
                parsed = json.loads(item)
                turns.append(
                    {
                        "user": str(parsed.get("user", "")),
                        "assistant": str(parsed.get("assistant", "")),
                        "ts": str(parsed.get("ts", "")),
                    }
                )
            except json.JSONDecodeError:
                continue
        return turns

    def format_recent_history(self, session_id: str, limit: int = 5) -> List[str]:
        turns = self.get_recent_turns(session_id=session_id, limit=limit)
        lines: List[str] = []
        for idx, turn in enumerate(turns, start=1):
            lines.append(
                f"Round {idx}\nUser: {turn['user']}\nAssistant: {turn['assistant']}"
            )
        return lines
