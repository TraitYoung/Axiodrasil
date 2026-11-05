"""Bina 单角色、人设与痛感边界回归。"""

import unittest
from unittest.mock import MagicMock, patch

from agents.router import node_solo_fast
from modules.personas.adapter import PersonaCatalog
from prompts.system_prompts import BINA_PROMPT_TEMPLATE


class BinaTests(unittest.TestCase):
    def test_catalog_only_exposes_bina(self):
        catalog = PersonaCatalog()
        self.assertEqual([card.id for card in catalog.list_cards()], ["bina"])
        self.assertIsNone(catalog.get_card("bit"))

    def test_critical_input_keeps_bina_and_pain_signal(self):
        with patch("agents.router.get_mood_engine") as mood:
            state = node_solo_fast({"current_input": "心脏狂跳喘不上气", "thread_id": "user"})
        self.assertEqual(state["intent"].persona, "bina")
        self.assertGreater(state["intent"].pain_level, 6)
        mood.return_value.apply_pain_signal.assert_called_once_with("user", state["intent"].pain_level)

    def test_prompt_keeps_memory_correction_rules(self):
        prompt = BINA_PROMPT_TEMPLATE.format(visual_rule="视觉规则", medical_block="", mode_context="单聊")
        self.assertIn("更正", prompt)
        self.assertIn("共同经历", prompt)
        self.assertIn("口癖", prompt)


if __name__ == "__main__":
    unittest.main()
