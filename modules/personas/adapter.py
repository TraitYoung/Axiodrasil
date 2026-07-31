"""人设 / 角色卡 catalog（PersonaPort）。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from agents.persona_meta import PERSONA_META
from app.matrix.ports import PersonaCard

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CARD_DIR = _PROJECT_ROOT / "sillytavern" / "character_card" / "group"

PERSONA_COLORS: dict[str, str] = {
    "bina": "#c45c6a",
    "bit": "#3d7ea6",
    "taki": "#6b7280",
    "chizheng": "#8b5a2b",
    "tianji": "#5b7c5a",
    "fukucho": "#7a4d4d",
    "vinci": "#9a6b3f",
    "planck": "#4a6fa5",
    "jiafa": "#6b5b7a",
    "qianjin": "#a67c52",
    "boming": "#5c4a3a",
    "jean": "#4d6b5c",
}

GROUP_SESSION_ID = "ax-cabinet-main"

# 公开 catalog 仅暴露 Bina；完整 PERSONA_META 仍保留以便路由/历史/未来复制人格。
PUBLIC_PERSONA_IDS: tuple[str, ...] = ("bina",)


class PersonaCatalog:
    """从 PERSONA_META + group 角色卡 JSON 组装只读视图模型。"""

    def list_cards(self) -> list[PersonaCard]:
        cards: list[PersonaCard] = []
        for pid in PUBLIC_PERSONA_IDS:
            card = self.get_card(pid)
            if card:
                cards.append(card)
        return cards

    def get_card(self, persona_id: str) -> Optional[PersonaCard]:
        pid = (persona_id or "").strip().lower()
        if pid not in PERSONA_META:
            return None
        name, title = PERSONA_META[pid]
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
            color=PERSONA_COLORS.get(pid, "#8b7355"),
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
    """SessionPort：群聊固定命名空间 / 单人按人设隔离。"""

    def group_session_id(self) -> str:
        return GROUP_SESSION_ID

    def solo_session_id(self, persona_id: str, user_local_id: str) -> str:
        pid = (persona_id or "unknown").strip().lower()
        uid = (user_local_id or "local").strip() or "local"
        uid = "".join(ch for ch in uid if ch.isalnum() or ch in "-_")[:32] or "local"
        return f"ax-solo-{pid}-{uid}"

    def resolve(self, raw: Optional[str], *, fallback: str = "") -> str:
        if raw and str(raw).strip():
            return str(raw).strip()
        return fallback or GROUP_SESSION_ID
