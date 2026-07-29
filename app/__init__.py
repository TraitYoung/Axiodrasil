"""Axiodrasil Host：组装、注册模块、暴露统一接口矩阵。"""

__all__ = ["create_app"]


def create_app():
    from app.factory import create_app as _create

    return _create()
