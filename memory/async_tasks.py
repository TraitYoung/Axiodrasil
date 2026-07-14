"""
轻量异步任务调度：让记忆的细粒度提取/向量化/摘要不阻塞在线对话路径。

不引入 Celery（同步 LangGraph 图 + 偶发后台任务的场景没必要上消息队列）。
优先复用 FastAPI 请求生命周期自带的 `BackgroundTasks`；当调用方拿不到
`BackgroundTasks`（例如脱离 API 直接跑 `agents/router.py` 的图，或本地
`test_suite/`、`scripts/` 里的脚本）时，退化为一个后台线程池，保证同一套
调用方式在「在线请求」和「脚本/测试」两种场景下都不报错、不阻塞。
"""

from __future__ import annotations

import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

try:  # 可选依赖：只有在 FastAPI 请求上下文里才会真正用到
    from fastapi import BackgroundTasks
except ImportError:  # pragma: no cover - FastAPI 必然已安装，兜底以防环境缺失
    BackgroundTasks = None  # type: ignore[assignment]


_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ax-async")


def _safe_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    try:
        fn(*args, **kwargs)
    except Exception:
        # 异步任务失败不应该影响主对话路径；打印堆栈供本地调试即可。
        print(f"[async_tasks] 后台任务执行失败: {fn.__name__}")
        traceback.print_exc()


def schedule(
    fn: Callable[..., Any],
    *args: Any,
    background_tasks: Optional["BackgroundTasks"] = None,
    **kwargs: Any,
) -> None:
    """调度一个后台任务。

    - 若传入了 `background_tasks`（FastAPI 请求上下文），挂载到响应发送后执行。
    - 否则丢进线程池异步跑，调用方（当前请求/脚本）立即返回，不等待完成。
    """
    if background_tasks is not None:
        background_tasks.add_task(_safe_call, fn, *args, **kwargs)
        return
    _EXECUTOR.submit(_safe_call, fn, *args, **kwargs)


__all__ = ["schedule"]
