"""
TurnService：对话回合唯一内部入口。

HTTP / ChatAdapter / OpenAI 兼容层都应调用本服务，避免互相 import main。
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, List, Literal, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

from agents.persona_meta import SUMMON_ALIASES, PERSONA_TO_ROUTE
from agents.router import app as router_graph
from agents.workflow_pipelines import run_dev_pipeline, synthetic_intent_for_workflow
from infrastructure.container import get_llm, get_memory_db
from memory import async_tasks
from memory.cabinet_layers import (
    append_debate_exchange,
    close_and_compress,
    detect_consensus_close,
    extract_persona_private,
)
from memory.session_cache import SessionCache
from memory.session_history import append_turn, load_for_prompt, load_for_ui
from memory.summary_service import maybe_trigger_rolling_summary
from memory.turn_context import build_turn_context
from schemas.protocols import TaskIntent
from tracing.router_run import run_router_traced

WorkflowMode = Literal["default", "dev_pipeline"]


class TurnRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=12000)
    workflow_mode: WorkflowMode = "default"
    forced_persona: Optional[str] = None
    strip_persona_prefix: bool = False
    group_mode: Optional[bool] = None
    # 共享记忆池；缺省等于 session_id（conversation）
    memory_thread_id: Optional[str] = None


@dataclass
class TurnResult:
    reply: str
    intent: TaskIntent
    trace_raw: list
    active_task_type: str
    active_persona: str


_session_cache: Optional[SessionCache] = None


def get_shared_session_cache() -> SessionCache:
    global _session_cache
    if _session_cache is None:
        _session_cache = SessionCache(ttl_seconds=3600, window_size=5)
    return _session_cache


def _normalize_persona(token: Optional[str]) -> Optional[str]:
    if not token or not str(token).strip():
        return None
    raw = str(token).strip()
    mapped = SUMMON_ALIASES.get(raw) or SUMMON_ALIASES.get(raw.lower())
    if mapped and mapped in PERSONA_TO_ROUTE:
        return mapped
    return None


def resolve_group_mode(payload: TurnRequest) -> bool:
    if payload.group_mode is not None:
        return bool(payload.group_mode)
    return bool(payload.forced_persona)


def use_solo_fast(payload: TurnRequest) -> bool:
    """forced bina + 非群聊 → 跳过全量 parser。"""
    forced = _normalize_persona(payload.forced_persona)
    if forced != "bina":
        return False
    if resolve_group_mode(payload):
        return False
    return os.getenv("AX_SOLO_FAST", "1").strip() not in ("0", "false", "False")


class TurnService:
    def __init__(self, session_cache: Optional[SessionCache] = None) -> None:
        self.session_cache = session_cache or get_shared_session_cache()

    def load_history_ui(self, session_id: str, limit: int = 50) -> List[dict]:
        return load_for_ui(session_id, limit=limit, session_cache=self.session_cache)

    def run(self, payload: TurnRequest, session_id: str) -> TurnResult:
        conversation_id = session_id
        memory_thread_id = (payload.memory_thread_id or "").strip() or conversation_id

        if payload.workflow_mode == "dev_pipeline":
            reply_raw, trace_raw = run_dev_pipeline(payload.text, get_llm())
            intent = synthetic_intent_for_workflow(payload.text, task_type="bit")
            active_task_type = "dev_pipeline"
            active_persona = "bit"
        else:
            # L1 热历史按对话隔离
            recent_history = load_for_prompt(
                conversation_id, limit=5, session_cache=self.session_cache
            )
            solo_fast = use_solo_fast(payload)
            turn_ctx = build_turn_context(
                conversation_id,
                recent_history,
                memory_thread_id=memory_thread_id,
                prefetch_summary=True,
            )
            graph_state: dict[str, Any] = {
                "current_input": payload.text,
                # Mood / L3 / Q1Q2 归档走共享记忆池
                "thread_id": memory_thread_id,
                "conversation_id": conversation_id,
                "recent_history": recent_history,
                "turn_context": turn_ctx,
            }
            forced = _normalize_persona(payload.forced_persona)
            if forced:
                graph_state["forced_persona"] = forced
            if solo_fast:
                graph_state["solo_fast"] = True
            result, trace_raw = run_router_traced(router_graph, graph_state)
            reply_raw = str(result.get("final_response", ""))
            intent = result.get("intent")
            if intent is None:
                raise HTTPException(status_code=500, detail="router returned empty intent")
            active_task_type = result.get("active_task_type")
            if active_task_type is None:
                active_task_type = getattr(intent, "task_type", None)
            active_persona = result.get("active_persona") or getattr(intent, "persona", None)

        prefix_map = {
            "emotion": "bina",
            "jean": "jean",
            "bit": "bit",
            "juzheng": "juzheng",
            "unknown": "juzheng",
            "dev_pipeline": "dev",
        }
        prefix = (
            str(active_persona)
            if active_persona
            else prefix_map.get(str(active_task_type), "juzheng")
        )
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
        group_mode: bool,
        memory_thread_id: Optional[str] = None,
    ) -> str:
        conversation_id = session_id
        mem = (memory_thread_id or "").strip() or conversation_id

        labeled = reply_for_client
        if not re.match(r"^\s*\[[^\]]+]\s*[:：]", reply_for_client or ""):
            labeled = f"[{active_persona}]: {reply_for_client}"

        # L1 + 本对话 L2 计数/摘要
        append_turn(
            conversation_id,
            user_text,
            labeled,
            session_cache=self.session_cache,
        )
        maybe_trigger_rolling_summary(
            conversation_id, self.session_cache, get_memory_db()
        )

        clean_assistant = re.sub(r"^\s*\[[^\]]+]\s*[:：]\s*", "", labeled)

        if group_mode and active_persona:
            try:
                append_debate_exchange(
                    conversation_id,
                    user_text=user_text,
                    assistant_text=clean_assistant,
                    persona=active_persona,
                )
            except Exception as e:
                print(f"[cabinet] M1 write failed: {e}")

        # M2 私忆挂共享记忆池
        if active_persona:
            try:
                async_tasks.schedule(
                    extract_persona_private,
                    mem,
                    active_persona,
                    user_text=user_text,
                    assistant_text=clean_assistant,
                )
            except Exception as e:
                print(f"[cabinet] M2 schedule failed: {e}")

        if detect_consensus_close(user_text) or detect_consensus_close(reply_for_client):
            try:
                summary = close_and_compress(conversation_id)
                if summary:
                    print(f"[cabinet] consensus saved: {summary[:80]}...")
            except Exception as e:
                print(f"[cabinet] consensus failed: {e}")

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
    "get_shared_session_cache",
    "resolve_group_mode",
    "use_solo_fast",
]
