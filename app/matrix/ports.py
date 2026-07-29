"""
接口矩阵 Port 定义（第一版冻结）。

功能模块只依赖这些 Protocol + infra，禁止互相直连内部实现。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, Protocol


@dataclass(frozen=True)
class HealthStatus:
    ok: bool
    redis: bool = False
    llm_provider: str = ""
    chat_model: str = ""


@dataclass(frozen=True)
class ChatTurn:
    user: str
    assistant: str
    ts: str = ""
    persona: str = ""


@dataclass
class ChatStreamResult:
    session_id: str
    reply: str
    active_persona: str
    intent: dict[str, Any] = field(default_factory=dict)
    trace_id: str = ""
    trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class PersonaCard:
    id: str
    name: str
    title: str
    description: str = ""
    personality: str = ""
    greeting: str = ""
    model_id: str = ""
    color: str = "#8b7355"
    avatar: str = ""


@dataclass(frozen=True)
class TraceStepView:
    index: int
    node: str
    duration_ms: float
    summary: dict[str, Any] = field(default_factory=dict)


class HealthPort(Protocol):
    def check(self) -> HealthStatus: ...


class SessionPort(Protocol):
    def group_session_id(self) -> str: ...

    def solo_session_id(self, persona_id: str, user_local_id: str) -> str: ...

    def resolve(self, raw: Optional[str], *, fallback: str = "") -> str: ...


class ChatPort(Protocol):
    async def stream(
        self,
        text: str,
        *,
        session_id: str,
        forced_persona: Optional[str] = None,
        strip_persona_prefix: bool = False,
        workflow_mode: str = "default",
        trace_id: Optional[str] = None,
    ) -> ChatStreamResult: ...

    def history(self, session_id: str, *, limit: int = 50) -> list[ChatTurn]: ...

    def export(self, session_id: str, *, limit: int = 20) -> dict[str, Any]: ...


class PersonaPort(Protocol):
    def list_cards(self) -> list[PersonaCard]: ...

    def get_card(self, persona_id: str) -> Optional[PersonaCard]: ...


class CabinetPort(Protocol):
    def consensus(self, session_id: str) -> dict[str, Any]: ...

    def default_member_ids(self) -> list[str]: ...


class TracePort(Protocol):
    def last_steps(self, trace: list[dict[str, Any]]) -> list[TraceStepView]: ...
