from typing import Literal

from pydantic import BaseModel, Field, field_validator

# 内阁完整人格阵容（BIOS V17.0 Module 1）+ Jean（文档/RAG 功能性角色，不在 BIOS
# 人设阵容内，但承担现有 Hybrid RAG 检索职能，故一并保留在 persona 枚举里）。
PersonaName = Literal[
    # Tier 1: The Core（常驻神经元）
    "bina",
    "bit",
    "taki",
    "chizheng",
    # Tier 2: Specialists（按需触发）
    "tianji",
    "fukucho",
    "vinci",
    # Tier 3: The Think Tank（深层）
    "planck",
    "jiafa",
    "qianjin",
    "boming",
    # 功能性角色（非 BIOS 人设阵容，承担文档/RAG 检索）
    "jean",
]

# 注意：DOMAIN_DEFAULT_PERSONA 已迁移到 agents/persona_meta.py，
# 由 agents/route_resolver.py 和 agents/router.py 统一导入。
# 此处仅保留 PersonaName 类型定义供 schemas 层使用。


class TaskIntent(BaseModel):
    """核心输入解析协议 (V15.0 + persona 分层)"""

    task_type: Literal["emotion", "jean", "bit", "juzheng", "unknown"] = Field(
        ...,
        description="""任务分类路由标识（domain，大类）。只能是以下五个值之一：
        - emotion: 情绪疏导、安抚、吐槽、求支持；同时承接医疗红线熔断场景。
        - jean: 文档/资料管理（提炼要点、阅读路线、资料摘要、基于检索材料的组织表达）。
        - bit: 代码/专业知识管理（推导、审计、给可运行代码；必要时调用工具）。
        - juzheng: 战略管理（计划、步骤拆解、复盘框架、长期安排）。
        - unknown: 无法稳定判断时使用。
        绝对禁止输出 emotion、jean、bit、juzheng、unknown 之外的任何新标签。
        注意：juzheng 这个 domain 名称是历史遗留（对应 BIOS 人设 Chizheng），
        为了不牵动既有 API/前端字段而保留，具体人格名以 persona 字段为准。""",
    )
    persona: PersonaName = Field(
        default="chizheng",
        description=(
            "具体执勤人格（11 人 BIOS 阵容 + Jean）。此字段不要求大模型自行判断——"
            "parser 拿到 task_type 后会用 DOMAIN_DEFAULT_PERSONA 覆盖为确定性默认值，"
            "再由 route_by_intent 的关键词触发/召唤协议按需精细化，避免让大模型对"
            "11 个人格做不稳定的分类。"
        ),
    )
    urgency_level: int = Field(
        default=1, ge=1, le=5, description="紧急程度，范围只能是 1 到 5。"
    )
    pain_level: int = Field(
        default=1,
        ge=1,
        le=10,
        description="""身心痛感指标，范围只能是 1 到 10。
        - 1-3: 正常状态，或轻微脑力疲劳。
        - 4-6: 中度疲劳、情绪见底、抱怨、想哭、受挫，但没有严重躯体化症状。
        - 7-10: 只有明确提到严重生理反应，例如心脏狂跳、手抖、极度疼痛、呼吸困难、濒临昏厥等，才能打到这个区间。""",
    )
    raw_input: str = Field(
        ..., description="用户原始输入内容，必须原样保留，不允许省略。"
    )

    # 【新增：豪威尔记忆矩阵象限】
    quadrant: Literal["Q1", "Q2", "Q3", "Q4"] = Field(
        default="Q4",
        description=(
            "艾森豪威尔矩阵象限。"
            "Q1: 紧急重要(如健康预警), "
            "Q2: 重要不紧急(如技术积累), "
            "Q3: 紧急不重要(琐事), "
            "Q4: 不重要不紧急(废话)"
        ),
    )

    @field_validator("pain_level")
    def validate_pain(cls, v: int) -> int:
        if not (1 <= v <= 10):
            raise ValueError("pain_level 必须在 1-10 之间")
        if v > 6:
            print(f"[WARNING] 触发医疗红线！当前痛感判定为: {v}")
        return v

    @field_validator("urgency_level")
    def validate_urgency(cls, v: int) -> int:
        if not (1 <= v <= 5):
            raise ValueError("urgency_level 必须在 1-5 之间")
        return v