"""模块注册表：主体通过矩阵绑定各功能模块实现。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from app.matrix.ports import (
    CabinetPort,
    ChatPort,
    HealthPort,
    PersonaPort,
    SessionPort,
    TracePort,
)


@dataclass
class ModuleRegistry:
    health: Optional[HealthPort] = None
    session: Optional[SessionPort] = None
    chat: Optional[ChatPort] = None
    personas: Optional[PersonaPort] = None
    cabinet: Optional[CabinetPort] = None
    trace: Optional[TracePort] = None
    extras: dict[str, Any] = field(default_factory=dict)

    def require(self, name: str) -> Any:
        value = getattr(self, name, None)
        if value is None:
            raise RuntimeError(f"module not registered: {name}")
        return value


_REGISTRY: Optional[ModuleRegistry] = None


def get_registry() -> ModuleRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = ModuleRegistry()
    return _REGISTRY


def set_registry(registry: ModuleRegistry) -> ModuleRegistry:
    global _REGISTRY
    _REGISTRY = registry
    return _REGISTRY


def bootstrap_registry() -> ModuleRegistry:
    """装配默认适配器（包装现有 agents / memory / main 逻辑）。"""
    from modules.cabinet_memory.adapter import CabinetAdapter
    from modules.chat_api.adapter import ChatAdapter, HealthAdapter, TraceAdapter
    from modules.personas.adapter import PersonaCatalog, SessionAdapter

    reg = ModuleRegistry(
        health=HealthAdapter(),
        session=SessionAdapter(),
        chat=ChatAdapter(),
        personas=PersonaCatalog(),
        cabinet=CabinetAdapter(),
        trace=TraceAdapter(),
    )
    return set_registry(reg)
