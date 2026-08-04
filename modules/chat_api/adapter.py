"""
Chat / Health / Trace 适配器。

经 TurnService 执行回合，禁止反向 import main。
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from app.matrix.ports import ChatStreamResult, ChatTurn, HealthStatus, TraceStepView
from modules.chat_api.service import (
    TurnRequest,
    get_shared_session_cache,
    get_turn_service,
    resolve_group_mode,
)


class HealthAdapter:
    def check(self) -> HealthStatus:
        from infra import get_chat_model, get_llm_provider

        cache = get_shared_session_cache()
        return HealthStatus(
            ok=True,
            redis=cache.ping(),
            llm_provider=get_llm_provider(),
            chat_model=get_chat_model(),
        )


class TraceAdapter:
    def last_steps(self, trace: list[dict[str, Any]]) -> list[TraceStepView]:
        out: list[TraceStepView] = []
        for i, step in enumerate(trace or []):
            out.append(
                TraceStepView(
                    index=int(step.get("index", i)),
                    node=str(step.get("node", "")),
                    duration_ms=float(step.get("duration_ms") or 0),
                    summary=dict(step.get("summary") or {}),
                )
            )
        return out


class ChatAdapter:
    """包装 TurnService；供矩阵与脚本复用。"""

    async def stream(
        self,
        text: str,
        *,
        session_id: str,
        forced_persona: Optional[str] = None,
        strip_persona_prefix: bool = False,
        group_mode: Optional[bool] = None,
        workflow_mode: str = "default",
        trace_id: Optional[str] = None,
    ) -> ChatStreamResult:
        svc = get_turn_service()
        payload = TurnRequest(
            text=text,
            workflow_mode=workflow_mode,  # type: ignore[arg-type]
            forced_persona=forced_persona,
            strip_persona_prefix=strip_persona_prefix,
            group_mode=group_mode,
        )
        result = svc.run(payload, session_id)
        svc.after_turn(
            session_id,
            text,
            result.reply,
            result.active_persona,
            group_mode=resolve_group_mode(payload),
        )
        return ChatStreamResult(
            session_id=session_id,
            reply=result.reply,
            active_persona=result.active_persona,
            intent=result.intent.model_dump() if hasattr(result.intent, "model_dump") else {},
            trace_id=(trace_id or "").strip() or str(uuid4()),
            trace=list(result.trace_raw or []),
        )

    def history(self, session_id: str, *, limit: int = 50) -> list[ChatTurn]:
        import re

        turns = get_turn_service().load_history_ui(session_id, limit=limit)
        out: list[ChatTurn] = []
        for t in turns:
            assistant = t.get("assistant", "") or ""
            persona = ""
            m = re.match(r"^\s*\[([^\]]+)]\s*[:：]", assistant)
            if m:
                persona = m.group(1).strip().lower()
            out.append(
                ChatTurn(
                    user=t.get("user", "") or "",
                    assistant=assistant,
                    ts=t.get("ts", "") or "",
                    persona=persona,
                )
            )
        return out

    def export(self, session_id: str, *, limit: int = 20) -> dict[str, Any]:
        turns = self.history(session_id, limit=limit)
        return {
            "session_id": session_id,
            "turns": [
                {"user": t.user, "assistant": t.assistant, "ts": t.ts, "persona": t.persona}
                for t in turns
            ],
        }
