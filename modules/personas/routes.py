"""PersonaPort HTTP 面：角色卡 catalog。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.registry import get_registry
from modules.personas.adapter import PersonaCatalog

router = APIRouter(tags=["personas"])


class PersonaCardOut(BaseModel):
    id: str
    name: str
    title: str
    description: str = ""
    personality: str = ""
    greeting: str = ""
    model_id: str = ""
    color: str = "#8b7355"
    avatar: str = ""


class PersonaListOut(BaseModel):
    personas: list[PersonaCardOut] = Field(default_factory=list)


def _catalog() -> PersonaCatalog:
    reg = get_registry()
    personas = reg.personas
    if isinstance(personas, PersonaCatalog):
        return personas
    # 注册表尚未 bootstrap 时兜底
    return PersonaCatalog()


@router.get("/api/v1/personas", response_model=PersonaListOut)
def list_personas():
    cards = _catalog().list_cards()
    return PersonaListOut(
        personas=[
            PersonaCardOut(
                id=c.id,
                name=c.name,
                title=c.title,
                description=c.description,
                personality=c.personality,
                greeting=c.greeting,
                model_id=c.model_id,
                color=c.color,
                avatar=c.avatar,
            )
            for c in cards
        ]
    )


@router.get("/api/v1/personas/{persona_id}", response_model=PersonaCardOut)
def get_persona(persona_id: str):
    card = _catalog().get_card(persona_id)
    if not card:
        raise HTTPException(status_code=404, detail=f"persona not found: {persona_id}")
    return PersonaCardOut(
        id=card.id,
        name=card.name,
        title=card.title,
        description=card.description,
        personality=card.personality,
        greeting=card.greeting,
        model_id=card.model_id,
        color=card.color,
        avatar=card.avatar,
    )
