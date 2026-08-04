"""
后台异步的记忆细粒度处理：事实/偏好/情绪碎片提取 + 向量化 + 实体登记 + 滚动摘要。

不在 `agents/router.py` 的 `node_parser` 同步路径里做这些事——那里只管落
原始 Q1/Q2 内容（开销很小，保留同步）。细粒度提取需要额外一次 LLM 调用，
必须通过 `memory/async_tasks.py` 调度到后台执行，避免拖慢在线对话响应。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from infrastructure.container import (
    get_db_path,
    get_enrichment_extraction_llm,
    get_enrichment_llm,
)
from memory.database import PersonaMemory
from schemas.memory import MemoryExtraction
from tools.ai_client import get_embedding


def extract_and_store(
    thread_id: str,
    source_memory_id: int,
    content: str,
    db_path: str | None = None,
) -> None:
    """从一条 Q1/Q2 原始记忆中提取事实/偏好/情绪碎片 + 实体，写入
    memory_fragments / memory_fragment_embeddings / entities。

    设计为「失败不影响主流程」：任何一步异常只打印日志并 return，因为这个
    函数总是在后台任务里跑，调用方早已把响应还给用户了。
    """
    path = db_path or get_db_path()
    extraction_llm = get_enrichment_extraction_llm()
    if extraction_llm is None:
        print("[enrichment] 未配置聊天 LLM API Key，跳过细粒度提取。")
        return

    memory_db = PersonaMemory(db_path=path)

    try:
        result: MemoryExtraction = extraction_llm.invoke(
            [
                SystemMessage(
                    content=(
                        "你是记忆归档官。只根据给定内容提炼结构化记忆碎片，不要编造。"
                        "facts 是客观事实；preferences 是偏好/习惯；"
                        "emotion_snapshot 是一句话情绪概括（没有明显情绪就留空字符串）；"
                        "entities 是提到的人物/项目/关键词。都尽量简短。"
                    )
                ),
                HumanMessage(content=content),
            ]
        )
    except Exception as e:
        print(f"[enrichment] 细粒度提取失败: {e}")
        return

    fragment_texts: List[Tuple[str, str]] = []
    for f in result.facts:
        fragment_texts.append(("fact", f))
    for p in result.preferences:
        fragment_texts.append(("preference", p))
    if result.emotion_snapshot:
        fragment_texts.append(("emotion", result.emotion_snapshot))

    for fragment_type, text in fragment_texts:
        if not text.strip():
            continue
        fragment_id = memory_db.save_fragment(
            thread_id=thread_id,
            content=text,
            fragment_type=fragment_type,
            source_memory_id=source_memory_id,
        )
        try:
            embedding = get_embedding(text)
            memory_db.save_fragment_embedding(fragment_id, embedding.tobytes())
        except Exception as e:
            print(f"[enrichment] 碎片向量化失败（文本已落库，不影响关键词/实体召回）: {e}")

    for entity in result.entities:
        name = entity.name.strip()
        if not name:
            continue
        try:
            entity_id = memory_db.upsert_entity(thread_id, name, entity.entity_type)
            memory_db.link_entity(entity_id, source_memory_id, source="matrix")
        except Exception as e:
            print(f"[enrichment] 实体登记失败: {e}")


def embed_and_store_memory(
    memory_id: int,
    content: str,
    db_path: str | None = None,
) -> None:
    """在线为一条 matrix 记忆写 embedding，避免仅依赖 scripts/migration.py 冷启动。"""
    if not content or not str(content).strip():
        return
    memory_db = PersonaMemory(db_path=db_path or get_db_path())
    try:
        embedding = get_embedding(content)
        memory_db.save_memory_embedding(memory_id, embedding.tobytes())
    except Exception as e:
        print(f"[enrichment] matrix 在线向量化失败（文本已落库）: {e}")


def generate_rolling_summary(
    thread_id: str,
    turns: List[Dict[str, Any]],
    db_path: str | None = None,
) -> None:
    """把最近若干轮（来自 Redis 会话热缓存）压成一段摘要，写入 memory_summaries。

    有意选择摘要"当前可拿到的最近对话文本"（Redis 滑窗），而不是另建一张
    全量留存表——BIOS 的 Q3/Q4 设计本身就是"主动遗忘"，这里不做庇护所式的
    "全量底片"。摘要只是把 Redis 5 轮窗口之外、L3 长期记忆之内的中期信息
    补一层，属于"力所能及范围内"的滚动摘要，不是不可篡改的完整历史。
    """
    llm = get_enrichment_llm()
    if llm is None or not turns:
        return

    transcript = "\n".join(
        f"User: {t.get('user', '')}\nAssistant: {t.get('assistant', '')}" for t in turns
    )

    try:
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "你是内阁的档案官。把下面这段对话压缩成 3-6 句话的中期摘要，"
                        "保留关键事实、决定、未解决的问题，不要逐句复述，不要加入没有出现过的内容。"
                    )
                ),
                HumanMessage(content=transcript),
            ]
        )
        summary_text = str(response.content)
    except Exception as e:
        print(f"[enrichment] 滚动摘要生成失败: {e}")
        return

    memory_db = PersonaMemory(db_path=db_path or get_db_path())
    start_ts = str(turns[0].get("ts", ""))
    end_ts = str(turns[-1].get("ts", ""))
    memory_db.save_summary(
        thread_id=thread_id,
        summary=summary_text,
        range_start_ts=start_ts,
        range_end_ts=end_ts,
        turn_count=len(turns),
    )
    memory_db.reset_turn_counter(thread_id)


__all__ = ["extract_and_store", "embed_and_store_memory", "generate_rolling_summary"]
