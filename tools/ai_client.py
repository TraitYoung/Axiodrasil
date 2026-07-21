"""
嵌入客户端薄封装：委托给 infrastructure.container 管理的单例。

保留 get_embedding 函数签名不变，所有调用方无需修改。
"""

from __future__ import annotations

from typing import List

import numpy as np

from infrastructure.container import get_embeddings_client


def get_embedding(text: str) -> np.ndarray:
    """
    调用 Qwen DashScope text-embedding-v2，返回 1536 维 float32 向量。
    """
    client = get_embeddings_client()
    vec: List[float] = client.embed_query(text)
    return np.asarray(vec, dtype=np.float32)


__all__ = ["get_embedding"]
