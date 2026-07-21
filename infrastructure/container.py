"""
集中创建共享实例：LLM、记忆、状态引擎、嵌入客户端。

所有需要这些对象的模块都应从这里获取，而不是各自 load_dotenv + new ChatOpenAI。
一处改配置，全局生效。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# 唯一的 .env 加载入口
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")

# ── 配置读取 ──────────────────────────────────────────
_QWEN_API_KEY = os.getenv("QWEN_API_KEY") or ""
_QWEN_BASE_URL = os.getenv(
    "QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
_enrichment_model = os.getenv("AX_ENRICHMENT_MODEL", "qwen-turbo")
_SUMMARY_EVERY_N_TURNS = int(os.getenv("AX_SUMMARY_EVERY_N_TURNS", "20"))

_DB_PATH = str(_PROJECT_ROOT / "data" / "axiodrasil_core.db")


# ── 延迟初始化的单例 ──────────────────────────────────
_llm = None
_enrichment_llm = None
_memory_db = None
_mood_engine = None
_embeddings_client = None


def get_llm():
    """主聊天 LLM（qwen-plus）"""
    global _llm
    if _llm is not None:
        return _llm
    if not _QWEN_API_KEY:
        print("⚠️ 未检测到 QWEN_API_KEY，LLM 调用将在首次 invoke 时报错。请检查 .env 文件！")
    from langchain_openai import ChatOpenAI

    _llm = ChatOpenAI(
        model="qwen-plus",
        api_key=_QWEN_API_KEY or "missing-key-will-fail-on-invoke",
        base_url=_QWEN_BASE_URL,
    )
    return _llm


def get_enrichment_llm():
    """记忆细粒度提取/滚动摘要用的轻量 LLM（qwen-turbo）"""
    global _enrichment_llm
    if _enrichment_llm is not None:
        return _enrichment_llm
    if not _QWEN_API_KEY:
        return None
    from langchain_openai import ChatOpenAI

    _enrichment_llm = ChatOpenAI(
        model=_enrichment_model,
        api_key=_QWEN_API_KEY,
        base_url=_QWEN_BASE_URL,
    )
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
    """DashScope 嵌入客户端（text-embedding-v2, 1536 维）"""
    global _embeddings_client
    if _embeddings_client is not None:
        return _embeddings_client
    if not _QWEN_API_KEY:
        raise ValueError("未检测到 QWEN_API_KEY，请在 .env 中配置该值。")
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
]
