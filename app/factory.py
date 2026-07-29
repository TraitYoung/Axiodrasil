"""主体工厂：装配注册表并返回 FastAPI app（兼容 uvicorn main:app）。"""

from __future__ import annotations

from fastapi import FastAPI

from app.registry import bootstrap_registry, get_registry


def create_app() -> FastAPI:
    """
    组装 Host：
    1. bootstrap 接口矩阵适配器
    2. 复用根 main.py 已注册的路由（增量迁移，避免一次搬迁）
    3. 挂载 personas catalog 等模块路由
    """
    bootstrap_registry()
    # 延迟导入，避免与 main 的双向引用在模块加载期炸裂
    import main as legacy

    app: FastAPI = legacy.app
    app.state.matrix = get_registry()  # type: ignore[attr-defined]

    from modules.personas.routes import router as personas_router

    if not any(getattr(r, "path", None) == "/api/v1/personas" for r in app.routes):
        app.include_router(personas_router)

    return app
