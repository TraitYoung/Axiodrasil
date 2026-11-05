"""
集中创建共享实例：LLM、聊天记录和状态引擎。

所有需要这些对象的模块都应从这里获取，而不是各自 load_dotenv + new ChatOpenAI。
一处改配置，全局生效。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv

# 唯一的 .env 加载入口
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ── 配置读取 ──────────────────────────────────────────
# 兼容误写成 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL 的 .env（其它工具链命名）
_LLM_PROVIDER = (os.getenv("AX_LLM_PROVIDER") or "deepseek").strip().lower()
_CHAT_MODEL = (
    os.getenv("AX_CHAT_MODEL")
    or os.getenv("LLM_MODEL")
    or ("deepseek-v4-flash" if _LLM_PROVIDER == "deepseek" else "qwen-plus")
)

_DEEPSEEK_API_KEY = (
    os.getenv("DEEPSEEK_API_KEY") or os.getenv("LLM_API_KEY") or ""
).strip()
_DEEPSEEK_BASE_URL = (
    os.getenv("DEEPSEEK_BASE_URL")
    or os.getenv("LLM_BASE_URL")
    or "https://api.deepseek.com"
).strip()
if _DEEPSEEK_BASE_URL.rstrip("/").endswith("/v1"):
    # ChatOpenAI 会自己拼 /chat/completions；根地址不要带 /v1
    _DEEPSEEK_BASE_URL = _DEEPSEEK_BASE_URL.rstrip("/")[:-3] or "https://api.deepseek.com"
_DEEPSEEK_THINKING = os.getenv("AX_DEEPSEEK_THINKING", "0").strip().lower() not in (
    "0",
    "false",
    "off",
    "",
)

_QWEN_API_KEY = (os.getenv("QWEN_API_KEY") or "").strip()
_QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)

# 启动器会设 AX_DB_PATH 到 Windows 本地盘；勿落到 \\wsl$\... 否则 SQLite 易锁死数秒
_DB_PATH = (os.getenv("AX_DB_PATH") or "").strip() or str(
    _PROJECT_ROOT / "data" / "axiodrasil_core.db"
)


# ── 延迟初始化的单例 ──────────────────────────────────
_llm = None
_chat_history = None
_mood_engine = None


def get_llm_provider() -> str:
    return _LLM_PROVIDER


def get_chat_model() -> str:
    return _CHAT_MODEL


def _chat_credentials() -> tuple[str, str]:
    """返回 (api_key, base_url) 给主聊天。"""
    if _LLM_PROVIDER == "qwen":
        return _QWEN_API_KEY, _QWEN_BASE_URL
    return _DEEPSEEK_API_KEY, _DEEPSEEK_BASE_URL


def _chat_openai_kwargs(model: str) -> dict[str, Any]:
    api_key, base_url = _chat_credentials()
    if not api_key:
        label = "DEEPSEEK_API_KEY" if _LLM_PROVIDER == "deepseek" else "QWEN_API_KEY"
        print(f"[llm] missing {label}; first invoke will fail. Check .env")
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": api_key or "missing-key-will-fail-on-invoke",
        "base_url": base_url,
    }
    if _LLM_PROVIDER == "deepseek":
        thinking_type = "enabled" if _DEEPSEEK_THINKING else "disabled"
        kwargs["extra_body"] = {"thinking": {"type": thinking_type}}
    return kwargs


def get_llm():
    """主聊天 LLM（默认 deepseek-v4-flash）"""
    global _llm
    if _llm is not None:
        return _llm
    from langchain_openai import ChatOpenAI

    _llm = ChatOpenAI(**_chat_openai_kwargs(_CHAT_MODEL))
    return _llm


def get_chat_history():
    global _chat_history
    if _chat_history is None:
        from storage.chat_history import ChatHistory

        _chat_history = ChatHistory(_DB_PATH)
    return _chat_history


def get_mood_engine():
    """状态引擎"""
    global _mood_engine
    if _mood_engine is not None:
        return _mood_engine
    from state.mood_engine import MoodEngine

    _mood_engine = MoodEngine(db_path=_DB_PATH)
    return _mood_engine


def get_db_path() -> str:
    return _DB_PATH


__all__ = ["get_llm", "get_chat_history", "get_mood_engine", "get_db_path", "get_llm_provider", "get_chat_model"]
