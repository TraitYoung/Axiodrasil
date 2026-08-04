"""轻量观测 stub：无完整 JSONL 管线时供 proactive 等模块导入。"""

from __future__ import annotations

from typing import Any


def obs(module: str, event: str, **kwargs: Any) -> None:
    """兼容入口；当前仅打印到 stdout（Windows 控制台勿带 emoji）。"""
    extra = " ".join(f"{k}={v}" for k, v in kwargs.items() if k != "error")
    err = kwargs.get("error")
    suffix = f" err={err}" if err else ""
    line = f"[obs:{module}] {event}"
    if extra:
        line = f"{line} {extra}"
    print(f"{line}{suffix}".rstrip())


__all__ = ["obs"]
