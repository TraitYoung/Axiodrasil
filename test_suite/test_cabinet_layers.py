"""内阁三层记忆 + 强制人设解析回归（不依赖外网 LLM）。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# 测试用临时库：在 import container 之前不要强绑；直接测 PersonaMemory + 解析函数
from memory.database import PersonaMemory
from memory.context_inject import (
    compose_cabinet_context,
    format_debate_block,
    format_persona_private_block,
    format_consensus_block,
)
from agents.route_resolver import resolve_route
from schemas.protocols import TaskIntent
from datetime import datetime


def _intent(**kwargs) -> TaskIntent:
    base = dict(
        task_type="emotion",
        persona="bina",
        urgency_level=2,
        pain_level=1,
        quadrant="Q4",
        raw_input="test",
    )
    base.update(kwargs)
    return TaskIntent(**base)


def test_forced_persona_and_medical_break():
    persona, route = resolve_route(
        _intent(pain_level=1),
        "随便聊聊",
        datetime.now(),
        forced_persona="bit",
    )
    assert persona == "bit" and route == "bit_route"

    persona, route = resolve_route(
        _intent(pain_level=9, raw_input="胸口剧痛"),
        "胸口剧痛",
        datetime.now(),
        forced_persona="bit",
    )
    assert persona == "bina" and route == "emotion_route"
    print("OK forced_persona + medical break")


def test_three_layers_isolation():
    td = tempfile.mkdtemp()
    db_path = str(Path(td) / "t.db")
    try:
        db = PersonaMemory(db_path=db_path)
        tid = "test-cabinet-thread"

        db.open_debate(tid)
        db.append_debate_turn(tid, "user", "user", "要不要通宵肝代码？")
        db.append_debate_turn(tid, "bit", "assistant", "可以，把 pipeline 先跑通。")
        db.append_debate_turn(tid, "bina", "assistant", "不行，先睡觉。")

        db.save_fragment(tid, "我认为陛下需要硬刚", "preference", persona="bit")
        db.save_fragment(tid, "陛下最近情绪脆弱", "preference", persona="bina")
        db.save_consensus(
            tid,
            summary="上周已约定：工作日 23:30 后不肝代码",
            conclusions="- 23:30 停工",
            unresolved="",
            action_items="- 副长盯梢",
            source_turn_count=4,
        )

        bit_ctx = compose_cabinet_context(db, tid, "bit")
        bina_ctx = compose_cabinet_context(db, tid, "bina")

        assert "吵架层" in bit_ctx and "pipeline" in bit_ctx
        assert "共识层" in bit_ctx and "23:30" in bit_ctx
        assert "硬刚" in bit_ctx
        assert "情绪脆弱" not in bit_ctx  # M2 隔离
        assert "情绪脆弱" in bina_ctx
        assert "硬刚" not in bina_ctx

        db.clear_debate_turns(tid)
        db.close_debate(tid)
        assert format_debate_block(db, tid) == ""
        assert "共识" in format_consensus_block(db, tid)
        assert "硬刚" in format_persona_private_block(db, tid, "bit")
        print("OK three-layer isolation + close")
    finally:
        try:
            import shutil
            shutil.rmtree(td, ignore_errors=True)
        except Exception:
            pass


def test_main_persona_resolvers():
    # 延迟导入，避免改坏全局 container 单例测试
    import main as m

    assert m._normalize_persona("郅政") == "chizheng"
    assert m._persona_from_model("axiodrasil-bina") == "bina"
    assert m._persona_from_model("bit") == "bit"
    msgs = [m.OpenAIChatMessage(role="system", content="hi [AX_PERSONA:taki]")]
    assert m._persona_from_messages(msgs) == "taki"
    assert (
        m._resolve_forced_persona(
            x_persona="jean", model="axiodrasil-bit", messages=msgs
        )
        == "jean"
    )
    print("OK persona resolvers")


if __name__ == "__main__":
    test_forced_persona_and_medical_break()
    test_three_layers_isolation()
    test_main_persona_resolvers()
    print("ALL PASSED")
