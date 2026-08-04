"""Solo fast-path 规则：痛感/象限启发式（无 LLM）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agents.solo_fast import estimate_pain_level, estimate_quadrant, synthesize_solo_bina_intent


def test_pain_critical():
    assert estimate_pain_level("心脏狂跳喘不上气") > 6
    assert estimate_pain_level("今天天气不错") < 4


def test_quadrant():
    assert estimate_quadrant("长期架构规划", pain_level=2) == "Q2"
    assert estimate_quadrant("随便聊聊", pain_level=2) == "Q4"
    assert estimate_quadrant("x", pain_level=8) == "Q1"


def test_synthesize():
    intent = synthesize_solo_bina_intent("陛下想吐槽一下")
    assert intent.persona == "bina"
    assert intent.task_type == "emotion"
    assert intent.raw_input == "陛下想吐槽一下"


if __name__ == "__main__":
    test_pain_critical()
    test_quadrant()
    test_synthesize()
    print("ok")
