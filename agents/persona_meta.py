"""
人格元数据 + 路由表（纯数据，不含行为逻辑）。

从 agents/router.py 抽出，便于 route_resolver、tracing 等模块共享，
避免循环依赖。
"""

from __future__ import annotations

from typing import Literal

# ── 人格枚举（与 schemas/protocols.py 的 PersonaName 保持一致）──────────
PersonaName = Literal[
    "bina", "bit", "taki", "chizheng",
    "tianji", "fukucho", "vinci",
    "planck", "jiafa", "qianjin", "boming",
    "jean",
]

# ── domain → 默认执勤人格 ──────────────────────────────────────────────
# domain 是粗分类（兼容现有 4 类路由），persona 是 11+1 人格里具体哪一个。
DOMAIN_DEFAULT_PERSONA: dict[str, PersonaName] = {
    "emotion": "bina",
    "jean": "jean",
    "bit": "bit",
    "juzheng": "chizheng",
    "unknown": "chizheng",
}

# ── BIOS Module 3 名片格式 ─────────────────────────────────────────────
PERSONA_META: dict[str, tuple[str, str]] = {
    "bina": ("Bina", "首席私人秘书"),
    "bit": ("Bit", "技术负责人"),
    "taki": ("Taki", "逻辑防火墙"),
    "chizheng": ("郅政", "首席战略官"),
    "tianji": ("天机", "情报大臣"),
    "fukucho": ("副长", "纪律大臣"),
    "vinci": ("达文西", "艺术大臣"),
    "planck": ("普朗克", "数学大臣"),
    "jiafa": ("稼发", "政治大臣"),
    "qianjin": ("千金", "医官"),
    "boming": ("伯明", "军师"),
    "jean": ("Jean", "文档管理官"),
}

# ── 召唤协议别名表 ──────────────────────────────────────────────────────
SUMMON_ALIASES: dict[str, str] = {
    "bina": "bina", "bit": "bit", "taki": "taki",
    "chizheng": "chizheng", "郅政": "chizheng", "居正": "chizheng", "juzheng": "chizheng",
    "tianji": "tianji", "天机": "tianji",
    "fukucho": "fukucho", "副长": "fukucho",
    "vinci": "vinci", "达文西": "vinci",
    "planck": "planck", "普朗克": "planck",
    "jiafa": "jiafa", "稼发": "jiafa",
    "qianjin": "qianjin", "千金": "qianjin",
    "boming": "boming", "伯明": "boming",
    "jean": "jean",
}

# ── persona → 条件边路由 key ────────────────────────────────────────────
PERSONA_TO_ROUTE: dict[str, str] = {
    "bina": "emotion_route", "jean": "jean_route", "bit": "bit_route",
    "taki": "taki_route", "chizheng": "juzheng_route",
    "tianji": "tianji_route", "fukucho": "fukucho_route", "vinci": "vinci_route",
    "planck": "planck_route", "jiafa": "jiafa_route",
    "qianjin": "qianjin_route", "boming": "boming_route",
}

# ── 条件边路由 key → 图节点名 ───────────────────────────────────────────
ROUTE_TO_NODE: dict[str, str] = {
    "emotion_route": "emotion_agent",
    "jean_route": "jean_agent",
    "bit_route": "bit_agent",
    "juzheng_route": "juzheng_agent",
    "taki_route": "taki_agent",
    "tianji_route": "tianji_agent",
    "fukucho_route": "fukucho_agent",
    "vinci_route": "vinci_agent",
    "planck_route": "planck_agent",
    "jiafa_route": "jiafa_agent",
    "qianjin_route": "qianjin_agent",
    "boming_route": "boming_agent",
    "debate_route": "debate_agent",
}

# ── 关键词触发表 ────────────────────────────────────────────────────────
CLEANING_KEYWORDS = ["json", "jsonl", "清洗", "归档", "sft", "logs", "log", "system instruction"]
FATIGUE_KEYWORDS = ["好累", "不想动", "困", "没精神", "没力气", "头疼", "腰疼", "肩颈疼"]
SHOPPING_KEYWORDS = ["值不值", "值得买", "要不要买", "防骗", "避雷", "劝退", "哪个牌子", "谁家的", "种草"]
ART_KEYWORDS = ["配色", "排版", "设计感", "画一个", "logo", "字体设计", "视觉稿", "画面感"]
TAKI_KEYWORDS = ["审计", "逻辑漏洞", "理一下逻辑", "复盘逻辑", "数据整洁", "归档整理一下"]
MATH_KEYWORDS = ["积分", "矩阵", "证明一下", "概率论", "线性代数", "微分方程", "级数"]
POLITICS_KEYWORDS = ["马原", "毛概", "史纲", "思修", "考研政治", "时政热点"]
BOMING_KEYWORDS = ["破局", "有什么妙计", "帮我出个主意", "山人", "锦囊"]
CONTINUED_WORK_KEYWORDS = ["学习", "复习", "敲代码", "写代码", "写作业", "肝", "赶进度", "写论文", "刷题"]
INDULGENCE_KEYWORDS = ["想买", "犒劳自己", "奖励自己", "剁手"]
CONFLICT_KEYWORDS = ["贵", "纠结", "要不要", "值不值", "花这个钱"]

__all__ = [
    "PersonaName",
    "DOMAIN_DEFAULT_PERSONA",
    "PERSONA_META",
    "SUMMON_ALIASES",
    "PERSONA_TO_ROUTE",
    "ROUTE_TO_NODE",
    "CLEANING_KEYWORDS",
    "FATIGUE_KEYWORDS",
    "SHOPPING_KEYWORDS",
    "ART_KEYWORDS",
    "TAKI_KEYWORDS",
    "MATH_KEYWORDS",
    "POLITICS_KEYWORDS",
    "BOMING_KEYWORDS",
    "CONTINUED_WORK_KEYWORDS",
    "INDULGENCE_KEYWORDS",
    "CONFLICT_KEYWORDS",
]
