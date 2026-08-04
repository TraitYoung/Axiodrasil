"""
Bina 主动找你：空闲心跳 + 阈值触发短讯。

由 FastAPI lifespan 启动后台任务；托盘轮询 pending 通知。
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from infrastructure.container import get_llm, get_mood_engine
from prompts.system_prompts import BINA_PROMPT_TEMPLATE, with_mood_context

PROACTIVE_USER_MARKER = "[proactive]"


def _log(event: str, **kwargs) -> None:
    try:
        from observability import obs  # type: ignore

        obs("mood", event, **kwargs)
        return
    except Exception:
        pass
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if k != "error")
    err = kwargs.get("error")
    suffix = f" err={err}" if err else ""
    print(f"[proactive] {event} {extra}{suffix}".rstrip())


def _env_flag(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip() not in ("0", "false", "False")


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


@dataclass
class PresenceTarget:
    session_id: str
    memory_thread_id: str
    updated_at: float = field(default_factory=time.time)


@dataclass
class PendingNotice:
    id: str
    session_id: str
    memory_thread_id: str
    preview: str
    created_at: str
    consumed: bool = False


_lock = threading.Lock()
_presence: Optional[PresenceTarget] = None
_pending: list[PendingNotice] = []
_last_contact_at: dict[str, float] = {}
_persist_turn_fn: Any = None
_loop_task: Optional[asyncio.Task] = None


def set_persist_turn(fn) -> None:
    """由 main 注入，避免 proactive ↔ main 循环导入。"""
    global _persist_turn_fn
    _persist_turn_fn = fn


def set_presence(session_id: str, memory_thread_id: str | None = None) -> PresenceTarget:
    global _presence
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id required")
    mem = (memory_thread_id or "").strip() or sid
    target = PresenceTarget(session_id=sid, memory_thread_id=mem)
    with _lock:
        _presence = target
    return target


def get_presence() -> Optional[PresenceTarget]:
    with _lock:
        return _presence


def drain_pending(*, mark_consumed: bool = True) -> list[dict]:
    with _lock:
        items = [p for p in _pending if not p.consumed]
        if mark_consumed:
            for p in items:
                p.consumed = True
        return [
            {
                "id": p.id,
                "session_id": p.session_id,
                "memory_thread_id": p.memory_thread_id,
                "preview": p.preview,
                "created_at": p.created_at,
            }
            for p in items
        ]


def _in_quiet_hours(now: Optional[datetime] = None) -> bool:
    now = now or datetime.now()
    start = _env_int("AX_PROACTIVE_QUIET_START", 0)
    end = _env_int("AX_PROACTIVE_QUIET_END", 8)
    hour = now.hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    # 跨午夜，如 23–7
    return hour >= start or hour < end


def _cooldown_ok(memory_thread_id: str) -> bool:
    cooldown_min = _env_float("AX_PROACTIVE_COOLDOWN_MIN", 45.0)
    with _lock:
        last = _last_contact_at.get(memory_thread_id)
    if last is None:
        return True
    return (time.time() - last) >= cooldown_min * 60.0


def _mark_contacted(memory_thread_id: str) -> None:
    with _lock:
        _last_contact_at[memory_thread_id] = time.time()


def _generate_bina_line(memory_thread_id: str) -> str:
    from prompts.bina_context import build_bina_mode_context

    mood = get_mood_engine()
    mode_context, visual_rule = build_bina_mode_context(proactive=True)
    base = BINA_PROMPT_TEMPLATE.format(
        visual_rule=visual_rule,
        medical_block="",
        mode_context=mode_context,
    )
    from prompts.steering import with_style_steering

    prompt = with_style_steering(
        with_mood_context(
            base,
            mood.get_prompt_context(memory_thread_id),
            mood.get_style_guidance(memory_thread_id),
        ),
        "bina",
    )
    human = (
        "【系统任务·主动开口】陛下一段时间没来找你了。请你像私下聊天一样先说一句短话"
        "（1–2 句，不超过 60 字）。可以轻轻问在不在、忙完了没，或分享一句很小的事。"
        "不要列表、不要客服腔、不要以 [Bina]: 开头。"
    )
    resp = get_llm().invoke(
        [SystemMessage(content=prompt), HumanMessage(content=human)]
    )
    text = str(getattr(resp, "content", "") or "").strip()
    text = text.replace("[Bina]:", "").replace("[bina]:", "").strip()
    if len(text) > 120:
        text = text[:117] + "…"
    return text or "陛下？忙完了吗，Bina 在这儿呢。"


def _enqueue_pending(session_id: str, memory_thread_id: str, preview: str) -> None:
    notice = PendingNotice(
        id=uuid.uuid4().hex[:12],
        session_id=session_id,
        memory_thread_id=memory_thread_id,
        preview=preview[:80],
        created_at=datetime.now().isoformat(timespec="seconds"),
    )
    with _lock:
        _pending.append(notice)
        # 只保留最近 20 条
        if len(_pending) > 20:
            del _pending[:-20]


def run_proactive_once() -> Optional[str]:
    """执行一次空闲判定；若开口返回助手文本，否则 None。"""
    if not _env_flag("AX_PROACTIVE_ENABLED", "1"):
        return None
    if _in_quiet_hours():
        return None

    presence = get_presence()
    if presence is None:
        return None

    mem = presence.memory_thread_id
    session_id = presence.session_id
    if not _cooldown_ok(mem):
        return None

    mood = get_mood_engine()
    mood.tick_idle(mem)
    triggers = mood.check_triggers(mem)
    if "contact" not in triggers:
        if "observation" in triggers:
            _log("proactive.observation", session_id=session_id, memory_thread_id=mem)
        return None

    try:
        line = _generate_bina_line(mem)
    except Exception as e:
        _log("proactive.generate_failed", error=e)
        return None

    labeled = f"[Bina]: {line}"
    if _persist_turn_fn is not None:
        try:
            _persist_turn_fn(session_id, PROACTIVE_USER_MARKER, labeled)
        except Exception as e:
            _log("proactive.persist_failed", error=e)
            return None

    mood.apply_delta(mem, connection=-0.35)
    _mark_contacted(mem)
    _enqueue_pending(session_id, mem, line)
    _log(
        "proactive.contact",
        session_id=session_id,
        memory_thread_id=mem,
        preview=line[:60],
    )
    return labeled


async def _heartbeat_loop() -> None:
    interval = max(30, _env_int("AX_PROACTIVE_INTERVAL_SEC", 300))
    _log("proactive.loop_start", interval_sec=interval)
    while True:
        try:
            await asyncio.to_thread(run_proactive_once)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _log("proactive.loop_error", error=e)
        await asyncio.sleep(interval)


async def start_proactive_loop() -> None:
    global _loop_task
    if not _env_flag("AX_PROACTIVE_ENABLED", "1"):
        _log("proactive.disabled")
        return
    if _loop_task is not None and not _loop_task.done():
        return
    _loop_task = asyncio.create_task(_heartbeat_loop())


async def stop_proactive_loop() -> None:
    global _loop_task
    if _loop_task is None:
        return
    _loop_task.cancel()
    try:
        await _loop_task
    except asyncio.CancelledError:
        pass
    _loop_task = None
    _log("proactive.loop_stop")


__all__ = [
    "PROACTIVE_USER_MARKER",
    "set_persist_turn",
    "set_presence",
    "get_presence",
    "drain_pending",
    "run_proactive_once",
    "start_proactive_loop",
    "stop_proactive_loop",
]
