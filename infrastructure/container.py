"""
集中创建共享实例：LLM、记忆、状态引擎、嵌入客户端。

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
_ENRICHMENT_MODEL = os.getenv("AX_ENRICHMENT_MODEL") or _CHAT_MODEL

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

_SUMMARY_EVERY_N_TURNS = int(os.getenv("AX_SUMMARY_EVERY_N_TURNS", "20"))
# 启动器会设 AX_DB_PATH 到 Windows 本地盘；勿落到 \\wsl$\... 否则 SQLite 易锁死数秒
_DB_PATH = (os.getenv("AX_DB_PATH") or "").strip() or str(
    _PROJECT_ROOT / "data" / "axiodrasil_core.db"
)


# ── 延迟初始化的单例 ──────────────────────────────────
_llm = None
_enrichment_llm = None
_memory_db = None
_mood_engine = None
_embeddings_client = None


def get_llm_provider() -> str:
    return _LLM_PROVIDER


def get_chat_model() -> str:
    return _CHAT_MODEL


def _chat_credentials() -> tuple[str, str]:
    """返回 (api_key, base_url) 给主聊天 / enrichment。"""
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


def get_enrichment_llm():
    """记忆细粒度提取/滚动摘要/共识压缩用的 LLM"""
    global _enrichment_llm
    if _enrichment_llm is not None:
        return _enrichment_llm
    api_key, _ = _chat_credentials()
    if not api_key:
        return None
    from langchain_openai import ChatOpenAI

    _enrichment_llm = ChatOpenAI(**_chat_openai_kwargs(_ENRICHMENT_MODEL))
    return _enrichment_llm


def get_enrichment_extraction_llm():
    """带 structured output 的记忆提取 LLM"""
    from schemas.memory import MemoryExtraction

    base = get_enrichment_llm()
    if base is None:
        return None
    return base.with_structured_output(MemoryExtraction)


def get_memory_db():
    """L3 记忆矩阵（SQLite）"""
    global _memory_db
    if _memory_db is not None:
        return _memory_db
    from memory.database import PersonaMemory

    _memory_db = PersonaMemory(db_path=_DB_PATH)
    return _memory_db


def get_mood_engine():
    """状态引擎"""
    global _mood_engine
    if _mood_engine is not None:
        return _mood_engine
    from state.mood_engine import MoodEngine

    _mood_engine = MoodEngine(db_path=_DB_PATH)
    return _mood_engine


def get_embeddings_client():
    """DashScope 嵌入客户端（text-embedding-v2, 1536 维）——与聊天 provider 解耦。"""
    global _embeddings_client
    if _embeddings_client is not None:
        return _embeddings_client
    if not _QWEN_API_KEY:
        raise ValueError("未检测到 QWEN_API_KEY，embedding 仍依赖 DashScope，请在 .env 中配置。")
    from langchain_community.embeddings.dashscope import DashScopeEmbeddings

    _embeddings_client = DashScopeEmbeddings(
        model="text-embedding-v2",
        dashscope_api_key=_QWEN_API_KEY,
    )
    return _embeddings_client


def get_db_path() -> str:
    return _DB_PATH


def get_summary_every_n_turns() -> int:
    return _SUMMARY_EVERY_N_TURNS


__all__ = [
    "get_llm",
    "get_enrichment_llm",
    "get_enrichment_extraction_llm",
    "get_memory_db",
    "get_mood_engine",
    "get_embeddings_client",
    "get_db_path",
    "get_summary_every_n_turns",
    "get_llm_provider",
    "get_chat_model",
]
