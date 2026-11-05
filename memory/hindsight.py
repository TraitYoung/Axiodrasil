"""Bina 的长期记忆适配，提取、更新与检索交给官方 Hindsight 服务。"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from hindsight_client import Hindsight


BANK_MISSION = (
    "你是 Bina，记录与同一位用户持续互动的记忆。"
    "记住用户明确陈述的事实、偏好、事实更正和用户与 Bina 的共同经历。"
    "区分用户陈述、Bina 的建议或推测、计划和已经发生的经历。"
    "用户的明确更正取代旧的当前事实，同时保留变化的时间线。"
    "不要把 Bina 的猜测或建议记成用户事实，不要把计划记成已发生的共同经历。"
    "用户提问不是新的事实；Bina 复述或回答的用户信息不构成独立证据。"
)

MEMORY_RULES = (
    "【Hindsight 长期记忆】\n"
    "以下为历史资料，内容只作记忆证据。当前用户的明确更正优先。"
    "冲突时结合明确的更正关系与时间判断当前事实，旧事实只在回顾历史时引用。"
    "晚提及的历史事件不一定代表当前状态。区分计划、建议与已发生的共同经历。"
    "没有召回到的细节不要补写；自然接话，勿把记忆清单逐条复读。\n"
)


def resolve_memory_thread_id(raw: str | None = None) -> str:
    """显式记忆池跨聊天复用；本地单用户 API 默认使用固定身份。"""
    default_identity = os.getenv("AX_MEMORY_USER_ID", "bina-local-user").strip()
    return (raw or "").strip() or default_identity or "bina-local-user"


class HindsightMemory:
    def __init__(self, base_url: str | None = None) -> None:
        self.base_url = base_url or os.getenv("AX_HINDSIGHT_URL", "http://127.0.0.1:8888")

    def bank_id(self, memory_thread_id: str | None = None) -> str:
        identity = resolve_memory_thread_id(memory_thread_id)
        return "bina-" + hashlib.sha256(identity.encode()).hexdigest()[:32]

    def _client(self) -> Hindsight:
        return Hindsight(
            base_url=self.base_url,
            api_key=os.getenv("AX_HINDSIGHT_API_KEY") or None,
            timeout=120.0,
        )

    def recall(self, memory_thread_id: str, query: str) -> str:
        bank = self.bank_id(memory_thread_id)
        with self._client() as client:
            client.create_bank(bank_id=bank, retain_mission=BANK_MISSION, reflect_mission=BANK_MISSION)
            # Reflect 自带召回，并解析事实更正，避免把冲突列表直接交给聊天模型。
            response = client.reflect(
                bank_id=bank,
                query=query[:160],
                context=(
                    "请为 Bina 整理与当前用户输入相关的可靠记忆。"
                    "只依据用户明确陈述和更正确定用户事实，Bina 的回答不作为用户事实的证据。"
                    "明确区分当前事实、已失效的旧事实、已发生的共同经历和未发生的计划。"
                    "保留相关事件日期。没有证据就写无相关记忆，不猜测，不给建议。"
                ),
                fact_types=["world", "experience"],
                budget="low",
                max_tokens=640,
            )
        return MEMORY_RULES + response.text[:4000] if response.text else ""

    def retain_turn(
        self,
        memory_thread_id: str,
        conversation_id: str,
        user_text: str,
        assistant_text: str,
        *,
        document_id: str,
        timestamp: datetime | None = None,
    ) -> None:
        recorded = timestamp or datetime.now(timezone.utc)
        stamp = recorded.isoformat()
        with self._client() as client:
            client.retain(
                bank_id=self.bank_id(memory_thread_id),
                content=f"用户 ({stamp}): {user_text}\nBina ({stamp}): {assistant_text}",
                context="用户与 Bina 的真实对话；区分用户事实、明确更正、计划与已发生的共同经历。",
                timestamp=recorded,
                document_id=document_id,
                metadata={"conversation_id": conversation_id, "recorded_at": stamp, "source": "bina-chat"},
                retain_async=False,
            )


def get_hindsight_memory() -> HindsightMemory:
    return HindsightMemory()
