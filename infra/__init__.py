"""
Infra 层薄封装：转发至现有 infrastructure.container。

新代码请 `from infra import get_llm, get_memory_db, ...`，
便于后续把 container 真正迁入本包而不打断调用方。
"""

from infrastructure.container import (
    get_chat_model,
    get_embeddings_client,
    get_enrichment_llm,
    get_llm,
    get_llm_provider,
    get_memory_db,
    get_mood_engine,
    get_summary_every_n_turns,
)

__all__ = [
    "get_llm",
    "get_enrichment_llm",
    "get_llm_provider",
    "get_chat_model",
    "get_memory_db",
    "get_mood_engine",
    "get_embeddings_client",
    "get_summary_every_n_turns",
]
