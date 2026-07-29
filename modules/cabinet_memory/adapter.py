"""Cabinet / 散会共识适配（CabinetPort）。"""

from __future__ import annotations

from typing import Any

from agents.persona_meta import PERSONA_META
from memory.cabinet_layers import close_and_compress


class CabinetAdapter:
    def consensus(self, session_id: str) -> dict[str, Any]:
        sid = (session_id or "").strip()
        if not sid:
            raise ValueError("missing session_id")
        summary = close_and_compress(sid) or ""
        return {
            "session_id": sid,
            "ok": True,
            "summary": summary,
            "message": "已散会并写入共识" if summary else "无进行中的吵架缓冲，已关闭吵架状态",
        }

    def default_member_ids(self) -> list[str]:
        return list(PERSONA_META.keys())
