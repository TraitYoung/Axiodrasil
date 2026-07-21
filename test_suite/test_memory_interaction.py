"""
聊天记忆与交互闭环的轻量回归（不调用 LLM）。

运行：在项目根目录
  python test_suite/test_memory_interaction.py
"""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from memory.context_inject import (  # noqa: E402
    compose_user_message,
    format_fragments_block,
    format_summaries_block,
)
from memory.database import PersonaMemory  # noqa: E402
from memory.enrichment import embed_and_store_memory  # noqa: E402
from state.mood_engine import MoodEngine  # noqa: E402


def main() -> None:
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        mem = PersonaMemory(db_path=db_path)
        tid = "interaction-regression"

        mem.save_summary(tid, "用户在准备考研，重点是线性代数。", "t0", "t1", 5)
        mem.save_fragment(tid, "喜欢喝美式", "preference")
        mem.save_fragment(tid, "本周要交架构作业", "fact")
        summary = format_summaries_block(mem, tid)
        fragments = format_fragments_block(mem, tid)
        assert "线性代数" in summary, summary
        assert "美式" in fragments, fragments

        human = compose_user_message(
            "本轮：就这个继续",
            recent_history=["Round 1\nUser: 帮我看线性代数\nAssistant: 好的"],
            summary_block=summary,
            fragment_block=fragments,
        )
        assert "最近对话" in human and "就这个继续" in human

        mid = mem.save_memory(tid, "长期架构规划草稿", "Q2")
        # 无 API key 时 embed 会失败并打日志，不应抛出
        embed_and_store_memory(mid, "长期架构规划草稿", db_path=db_path)

        mem.append_chat_turn(tid, "u1", "a1")
        mem.append_chat_turn(tid, "u2", "a2")
        turns = mem.get_chat_turns(tid, limit=10)
        assert [t["user"] for t in turns] == ["u1", "u2"]
        hist = mem.format_chat_history(tid, limit=5)
        assert len(hist) == 2 and hist[0].startswith("Round 1")

        mood = MoodEngine(db_path=db_path)
        first = mood.arm_interaction_hook(tid)
        assert "首次" in first
        mood.tick(tid)
        assert "首次" in mood.get_prompt_context(tid)
        assert "首次" not in mood.get_prompt_context(tid)  # consumed

        old = (datetime.now() - timedelta(hours=3)).isoformat()
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                "UPDATE mood_state SET last_tick_at=? WHERE thread_id=?",
                (old, tid),
            )
            conn.commit()
        reunion = mood.arm_interaction_hook(tid)
        assert "两小时" in reunion
        mood.tick(tid)
        assert "两小时" in mood.get_prompt_context(tid)

        print("test_memory_interaction: OK")
    finally:
        try:
            os.remove(db_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
