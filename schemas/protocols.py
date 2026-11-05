"""Bina 回合状态协议。"""

from typing import Literal
from pydantic import BaseModel, Field


class TaskIntent(BaseModel):
    task_type: Literal["emotion"] = "emotion"
    persona: Literal["bina"] = "bina"
    urgency_level: int = Field(default=1, ge=1, le=5)
    pain_level: int = Field(default=1, ge=1, le=10)
    raw_input: str
