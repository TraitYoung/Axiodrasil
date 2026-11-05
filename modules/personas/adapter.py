"""人设 / 角色卡 catalog（PersonaPort）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from app.matrix.ports import PersonaCard

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CARD_DIR = _PROJECT_ROOT / "sillytavern" / "character_card" / "group"

# 当前仅运行 Bina，其他人物设定见 docs/characters。
PUBLIC_PERSONA_IDS: tuple[str, ...] = ("bina",)


class PersonaCatalog:
    """从 Bina 角色卡组装只读视图模型。"""

    def list_cards(self) -> list[PersonaCard]:
        cards: list[PersonaCard] = []
        for pid in PUBLIC_PERSONA_IDS:
            card = self.get_card(pid)
            if card:
                cards.append(card)
        return cards

    def get_card(self, persona_id: str) -> Optional[PersonaCard]:
        pid = (persona_id or "").strip().lower()
        if pid not in PUBLIC_PERSONA_IDS:
            return None
        name, title = "Bina", "虚拟具身实验伙伴"
        card_data = self._load_card_json(pid)
        description = ""
        personality = ""
        greeting = ""
        avatar = ""
        if card_data:
            description = str(card_data.get("description") or "")
            lines = [
                ln
                for ln in description.splitlines()
                if not ln.strip().upper().startswith("[AX_PERSONA:")
            ]
            description = "\n".join(lines).strip()
            personality = str(card_data.get("personality") or "")
            greeting = str(card_data.get("first_mes") or "")
            avatar = str(card_data.get("avatar") or "")
        if not description:
            description = f"{name} · {title}"
        return PersonaCard(
            id=pid,
            name=name,
            title=title,
            description=description,
            personality=personality,
            greeting=greeting,
            model_id=f"axiodrasil-{pid}",
            color="#c45c6a",
            avatar=avatar,
        )

    def _load_card_json(self, persona_id: str) -> Optional[dict]:
        path = _CARD_DIR / f"{persona_id}.json"
        if not path.is_file():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        data = raw.get("data") if isinstance(raw, dict) else None
        return data if isinstance(data, dict) else None


class SessionAdapter:
    """SessionPort：单人会话命名空间。"""

    def solo_session_id(self, persona_id: str, user_local_id: str) -> str:
        pid = (persona_id or "unknown").strip().lower()
        uid = (user_local_id or "local").strip() or "local"
        uid = "".join(ch for ch in uid if ch.isalnum() or ch in "-_")[:32] or "local"
        return f"ax-solo-{pid}-{uid}"

    def resolve(self, raw: Optional[str], *, fallback: str = "") -> str:
        if raw and str(raw).strip():
            return str(raw).strip()
        return fallback or "bina-local-user"
