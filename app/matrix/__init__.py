"""统一接口矩阵（Ports）——主体与功能模块之间的唯一契约面。"""

from app.matrix.ports import (
    CabinetPort,
    ChatPort,
    ChatStreamResult,
    ChatTurn,
    HealthPort,
    HealthStatus,
    PersonaCard,
    PersonaPort,
    SessionPort,
    TracePort,
    TraceStepView,
)

__all__ = [
    "HealthPort",
    "HealthStatus",
    "SessionPort",
    "ChatPort",
    "ChatTurn",
    "ChatStreamResult",
    "PersonaPort",
    "PersonaCard",
    "CabinetPort",
    "TracePort",
    "TraceStepView",
]
