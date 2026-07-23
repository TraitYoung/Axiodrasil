"""
记忆细粒度提取协议：事实 / 偏好 / 情绪碎片 + 实体，供 memory/enrichment.py 使用。
"""

from typing import List, Literal

from pydantic import BaseModel, Field


class ExtractedEntity(BaseModel):
    name: str = Field(..., description="人物/项目/关键词的名称，尽量用原文里出现的说法。")
    entity_type: Literal["person", "project", "keyword"] = Field(
        default="keyword", description="实体类型：person 人物 / project 项目 / keyword 关键词。"
    )


class MemoryExtraction(BaseModel):
    """从一段原始记忆内容中提炼出的结构化碎片，替代"整段原文直接向量化"的粗粒度方案。"""

    facts: List[str] = Field(
        default_factory=list, description="客观事实，简短的一句话，不超过 5 条；没有就留空列表。"
    )
    preferences: List[str] = Field(
        default_factory=list, description="偏好/习惯，简短的一句话，不超过 5 条；没有就留空列表。"
    )
    emotion_snapshot: str = Field(
        default="", description="对当前情绪状态的一句话概括；没有明显情绪就留空字符串。"
    )
    entities: List[ExtractedEntity] = Field(
        default_factory=list, description="提到的人物/项目/关键词，不超过 5 个。"
    )


class PersonaPrivateExtraction(BaseModel):
    """从一轮人设发言中提炼的「仅本人可见」私忆。"""

    private_notes: List[str] = Field(
        default_factory=list,
        description="该人设对局势/陛下的私有判断或立场，简短，不超过 4 条；没有就留空。",
    )


class ConsensusExtraction(BaseModel):
    """吵架层压缩进共识层的结构化结果。"""

    conclusions: List[str] = Field(
        default_factory=list, description="已拍板结论，简短条目，不超过 6 条。"
    )
    unresolved: List[str] = Field(
        default_factory=list, description="仍未决的分歧，简短条目，不超过 4 条。"
    )
    action_items: List[str] = Field(
        default_factory=list, description="共同行动项/承诺，简短条目，不超过 4 条。"
    )
    summary: str = Field(
        default="", description="一两句总述本次争执与结果；没有就留空。"
    )
