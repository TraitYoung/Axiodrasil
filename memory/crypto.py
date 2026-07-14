"""
敏感字段加解密的最小共享实现。

`PersonaMemory`（写入侧）和 `hybrid_engine.HybridRetriever`（读取/检索侧）都需要
对 `memory_matrix.content` 做加解密，抽成独立模块避免两处各写一份 Fernet 逻辑。

未设置 `AX_MEMORY_ENC_KEY` 时，`encrypt`/`decrypt` 都是恒等函数（明文直通），
不影响现有行为；设置了但值非法时会打印一次警告并降级为明文。
"""

from __future__ import annotations

import os
from typing import Optional

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover
    Fernet = None  # type: ignore[assignment]
    InvalidToken = Exception  # type: ignore[assignment]


def _load_fernet(explicit_key: Optional[str] = None) -> Optional["Fernet"]:
    key = explicit_key or os.getenv("AX_MEMORY_ENC_KEY")
    if not key:
        return None
    if Fernet is None:
        print("[memory.crypto] 未安装 cryptography，无法启用加密，将以明文存储。")
        return None
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except Exception as e:
        print(f"[memory.crypto] AX_MEMORY_ENC_KEY 无效（{e}），将以明文存储。")
        return None


_FERNET = _load_fernet()


def is_enabled() -> bool:
    return _FERNET is not None


def encrypt(plaintext: str) -> str:
    if _FERNET is None or plaintext is None:
        return plaintext
    return _FERNET.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(stored: str) -> str:
    if _FERNET is None or stored is None:
        return stored
    try:
        return _FERNET.decrypt(stored.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        # 加密开启前写入的历史明文数据，原样返回，不阻断读取。
        return stored


__all__ = ["encrypt", "decrypt", "is_enabled"]
