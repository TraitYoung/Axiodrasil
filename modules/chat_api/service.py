"""
TurnService：对话回合唯一内部入口。

HTTP / ChatAdapter / OpenAI 兼容层都应调用本服务，避免互相 import main。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, List, Literal, Optional
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field

from agents.router import app as router_graph
from infrastructure.container import get_chat_history
from memory.hindsight import get_hindsight_memory, resolve_memory_thread_id

from schemas.protocols import TaskIntent
from tracing.router_run import run_router_traced

WorkflowMode = Literal["default", "dev_pipeline"]


class TurnRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=12000)
    workflow_mode: WorkflowMode = "default"
    forced_persona: Optional[str] = None
    strip_persona_prefix: bool = False
    group_mode: Optional[bool] = None
    # 稳定用户记忆池，与 conversation 分离。
    memory_thread_id: Optional[str] = None


@dataclass
class TurnResult:
    reply: str
    intent: TaskIntent
    trace_raw: list
    active_task_type: str
    active_persona: str


class TurnService:
    def load_history_ui(self, session_id: str, limit: int = 50) -> List[dict]:
        return get_chat_history().get_turns(session_id, limit)

    def run(self, payload: TurnRequest, session_id: str) -> TurnResult:
        conversation_id = session_id
        memory_thread_id = resolve_memory_thread_id(payload.memory_thread_id)

        if payload.workflow_mode == "dev_pipeline":
            raise HTTPException(status_code=410, detail="开发流水线已归档，当前仅运行 Bina 虚拟具身实验。")

        recent_history = get_chat_history().format_for_prompt(conversation_id, limit=5)
        try:
            long_term_context = get_hindsight_memory().recall(memory_thread_id, payload.text)
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Hindsight 记忆召回失败，请检查本机记忆服务。") from exc
        graph_state: dict[str, Any] = {
            "current_input": payload.text,
            # 状态和长期记忆使用稳定用户身份。
            "thread_id": memory_thread_id,
            "conversation_id": conversation_id,
            "recent_history": recent_history,
            "long_term_context": long_term_context,
        }
        result, trace_raw = run_router_traced(router_graph, graph_state)
        reply_raw = str(result.get("final_response", ""))
        intent = result.get("intent")
        if intent is None:
            raise HTTPException(status_code=500, detail="router returned empty intent")
        active_task_type = result.get("active_task_type")
        if active_task_type is None:
            active_task_type = getattr(intent, "task_type", None)
        active_persona = result.get("active_persona") or getattr(intent, "persona", None)

        prefix = "bina"
        reply_clean = re.sub(r"^\s*\[[^\]]+]\s*[:：]\s*", "", str(reply_raw))
        reply_labeled = f"[{prefix}]: {reply_clean}"
        reply_out = reply_clean if payload.strip_persona_prefix else reply_labeled
        return TurnResult(
            reply=reply_out,
            intent=intent,
            trace_raw=list(trace_raw or []),
            active_task_type=str(active_task_type),
            active_persona=str(active_persona or prefix),
        )

    def after_turn(
        self,
        session_id: str,
        user_text: str,
        reply_for_client: str,
        active_persona: str,
        *,
        memory_thread_id: Optional[str] = None,
    ) -> str:
        conversation_id = session_id
        mem = resolve_memory_thread_id(memory_thread_id)

        labeled = reply_for_client
        if not re.match(r"^\s*\[[^\]]+]\s*[:：]", reply_for_client or ""):
            labeled = f"[{active_persona}]: {reply_for_client}"

        turn_id = get_chat_history().append_turn(conversation_id, user_text, labeled)

        clean_assistant = re.sub(r"^\s*\[[^\]]+]\s*[:：]\s*", "", labeled)

        try:
            get_hindsight_memory().retain_turn(
                mem,
                conversation_id,
                user_text,
                clean_assistant,
                document_id=f"bina-turn-{uuid4().hex}-{turn_id}",
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="对话已保存到本地，但 Hindsight 长期记忆写入失败。") from exc

        return labeled


_default_service: Optional[TurnService] = None


def get_turn_service() -> TurnService:
    global _default_service
    if _default_service is None:
        _default_service = TurnService()
    return _default_service


__all__ = [
    "TurnRequest",
    "TurnResult",
    "TurnService",
    "get_turn_service",
]
