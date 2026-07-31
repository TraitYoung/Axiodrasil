"""
Bina 单聊优先回归（尽量不依赖外网 LLM）。

覆盖：
- 公开 catalog 仅 Bina
- forced bina → emotion_route；医疗熔断不可绕过
- group_mode 解析：solo 显式 false / 群聊 true / 缺省回退
- solo 不写 M1，仍调度 M2 私忆
- Bina prompt 含单聊关键约束
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from agents.route_resolver import resolve_route, ROUTE_TO_NODE
from modules.personas.adapter import PUBLIC_PERSONA_IDS, PersonaCatalog
from prompts.system_prompts import BINA_PROMPT_TEMPLATE
from schemas.protocols import TaskIntent


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


def test_public_catalog_bina_only():
    assert PUBLIC_PERSONA_IDS == ("bina",)
    cards = PersonaCatalog().list_cards()
    assert len(cards) == 1
    assert cards[0].id == "bina"
    # get_card 仍可取其他人格（软归档，非删除）
    bit = PersonaCatalog().get_card("bit")
    assert bit is not None and bit.id == "bit"
    print("OK public catalog bina-only")


def test_forced_bina_route_and_medical_break():
    persona, route = resolve_route(
        _intent(pain_level=1),
        "今天心情一般",
        datetime.now(),
        forced_persona="bina",
    )
    assert persona == "bina"
    assert route == "emotion_route"
    assert ROUTE_TO_NODE[route] == "emotion_agent"

    persona, route = resolve_route(
        _intent(pain_level=9, raw_input="心脏狂跳手抖"),
        "心脏狂跳手抖还想继续肝",
        datetime.now(),
        forced_persona="bit",
    )
    assert persona == "bina" and route == "emotion_route"
    print("OK forced bina + medical break")


def test_group_mode_resolution():
    import main as m

    solo = m.ChatRequest(
        text="hi",
        forced_persona="bina",
        strip_persona_prefix=True,
        group_mode=False,
    )
    assert m._resolve_group_mode(solo) is False

    group = m.ChatRequest(
        text="hi",
        forced_persona="bina",
        strip_persona_prefix=True,
        group_mode=True,
    )
    assert m._resolve_group_mode(group) is True

    legacy = m.ChatRequest(text="hi", forced_persona="bina")
    assert m._resolve_group_mode(legacy) is True

    plain = m.ChatRequest(text="hi")
    assert m._resolve_group_mode(plain) is False
    print("OK group_mode resolution")


def test_solo_skips_m1_keeps_m2():
    import main as m

    calls = {"m1": 0, "m2": 0}

    def fake_m1(*_a, **_k):
        calls["m1"] += 1

    def fake_schedule(fn, *args, **kwargs):
        # extract_persona_private 经 async_tasks.schedule 调度
        name = getattr(fn, "__name__", "")
        if name == "extract_persona_private":
            calls["m2"] += 1
        return None

    with (
        patch.object(m, "_persist_turn"),
        patch.object(m, "maybe_trigger_rolling_summary"),
        patch.object(m, "get_memory_db", return_value=object()),
        patch.object(m, "append_debate_exchange", side_effect=fake_m1),
        patch.object(m.async_tasks, "schedule", side_effect=fake_schedule),
        patch.object(m, "detect_consensus_close", return_value=False),
    ):
        m._after_turn_memory(
            "ax-solo-bina-test",
            "今天有点累",
            "先喝口水，靠一会儿。",
            "bina",
            group_mode=False,
        )
        assert calls["m1"] == 0, "solo 不应写 M1"
        assert calls["m2"] == 1, "solo 应调度 M2"

        calls["m1"] = 0
        calls["m2"] = 0
        m._after_turn_memory(
            "ax-cabinet-main",
            "大家怎么看",
            "我觉得先睡。",
            "bina",
            group_mode=True,
        )
        assert calls["m1"] == 1
        assert calls["m2"] == 1
    print("OK solo skips M1 keeps M2")


def test_bina_prompt_template_contract():
    filled = BINA_PROMPT_TEMPLATE.format(
        visual_rule="视觉测试",
        medical_block="",
        mode_context="单人密谈 · 测试",
    )
    assert "先共情" in filled
    assert "客服" in filled
    assert "口癖" in filled
    assert "记忆使用边界" in filled
    assert "单人密谈 · 测试" in filled
    print("OK bina prompt contract")


if __name__ == "__main__":
    test_public_catalog_bina_only()
    test_forced_bina_route_and_medical_break()
    test_group_mode_resolution()
    test_solo_skips_m1_keeps_m2()
    test_bina_prompt_template_contract()
    print("\nAll Bina-first checks passed.")
