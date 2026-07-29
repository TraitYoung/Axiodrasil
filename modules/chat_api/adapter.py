"""
Chat / Health / Trace 适配器。

HTTP 路由仍由根 `main.py` 承载；本适配器供 Host 注册表与其他模块
通过矩阵调用，避免直连 FastAPI 细节。ChatAdapter.stream 走内部
同步执行路径（与 SSE 同源逻辑），便于脚本/测试复用。
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import uuid4

from app.matrix.ports import ChatStreamResult, ChatTurn, HealthStatus, TraceStepView


class HealthAdapter:
    def check(self) -> HealthStatus:
        from infra import get_chat_model, get_llm_provider
        from memory.session_cache import SessionCache

        redis_ok = False
        try:
            SessionCache(ttl_seconds=3600, window_size=5).client.ping()
            redis_ok = True
        except Exception:
            pass
        return HealthStatus(
            ok=True,
            redis=redis_ok,
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
    """包装 main._execute_turn / history；延迟 import 避免循环。"""

    async def stream(
        self,
        text: str,
        *,
        session_id: str,
        forced_persona: Optional[str] = None,
        strip_persona_prefix: bool = False,
        workflow_mode: str = "default",
        trace_id: Optional[str] = None,
    ) -> ChatStreamResult:
        import main as core

        payload = core.ChatRequest(
            text=text,
            workflow_mode=workflow_mode,  # type: ignore[arg-type]
            forced_persona=forced_persona,
            strip_persona_prefix=strip_persona_prefix,
        )
        reply, intent, trace_raw, _active, active_persona = core._execute_turn(
            payload, session_id
        )
        core._after_turn_memory(
            session_id,
            text,
            reply,
            active_persona,
            group_mode=bool(forced_persona),
        )
        return ChatStreamResult(
            session_id=session_id,
            reply=reply,
            active_persona=active_persona,
            intent=intent.model_dump() if hasattr(intent, "model_dump") else {},
            trace_id=(trace_id or "").strip() or str(uuid4()),
            trace=list(trace_raw or []),
        )

    def history(self, session_id: str, *, limit: int = 50) -> list[ChatTurn]:
        import main as core
        import re

        turns = core._load_history_turns(session_id, limit=limit)
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
        # 导出仍走 HTTP 层；此处仅返回 history 快照
        turns = self.history(session_id, limit=limit)
        return {
            "session_id": session_id,
            "turns": [
                {"user": t.user, "assistant": t.assistant, "ts": t.ts, "persona": t.persona}
                for t in turns
            ],
        }
