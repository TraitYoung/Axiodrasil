"""
Mood / 状态引擎（内阁共享的动态状态层）。

移植自开源项目「积温 (jiwen)」的五轴数值漂移思路，但做了两点改造以适配内阁场景：

1. 内阁是被动响应式的多助理系统，没有独立的主动消息通道，所以不移植积温的
   `tick()` 触发数组（contact / find_activity / observation）；只保留数值漂移 +
   自然语言翻译（`get_prompt_context` / `get_style_guidance`），供各人格节点在
   生成回复前注入 system prompt。
2. 情绪信号直接对接内阁已有的 `TaskIntent.pain_level`，不需要再跑一次 LLM 做
   情绪分类；时段维度对接 BIOS Module 0.4 的作息表（Morning/Focus/Refuel/
   Free Soul/Shutdown），驱动 immersion 与语气基调。

五轴（沿用积温命名）：
- connection  [0, 1]   连接需求：多久没交互了，想念感累积
- pride       [-1, 1]  骄傲：端着还是放软
- valence     [-1, 1]  愉悦度（Russell 情绪环状模型）
- arousal     [-1, 1]  唤醒度（正交于 valence）
- immersion   [0, 1]   沉浸度：当前专注/忙碌程度

数值只做数学漂移，不调用任何模型；每次 `node_parser` 收到新一轮用户输入时
`tick()` 一次，状态按 `thread_id` 持久化在 SQLite 单行表 `mood_state`。
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _decay_toward_zero(value: float, rate_per_min: float, minutes: float) -> float:
    if value == 0:
        return 0.0
    step = rate_per_min * minutes
    if value > 0:
        return max(0.0, value - step)
    return min(0.0, value + step)


def _hooks_enabled() -> bool:
    return os.getenv("AX_INTERACTION_HOOKS_ENABLED", "1").strip() not in ("0", "false", "False")


# BIOS Module 0.4 作息表（去掉 Refuel 的重叠区间，按小时精确切分）
_PERIODS: List[Tuple[int, int, str, str]] = [
    (8, 10, "morning", "自然唤醒，温和启动"),
    (10, 12, "focus", "高信噪比，逻辑闭环"),
    (12, 14, "refuel", "午餐闲聊，全员解锁"),
    (14, 18, "focus", "高信噪比，逻辑闭环"),
    (18, 23, "free_soul", "绝对娱乐豁免，晚间家庭模式"),
]

# BIOS：间隔超过 2 小时可触发久别欢迎
_REUNION_GAP_MINUTES = float(os.getenv("AX_REUNION_GAP_MINUTES", "120"))


def get_period(now: Optional[datetime] = None) -> Tuple[str, str]:
    """返回 (period_key, period_label)，对齐 BIOS Module 0.4 作息表。"""
    now = now or datetime.now()
    hour = now.hour
    for start, end, key, label in _PERIODS:
        if start <= hour < end:
            return key, label
    return "shutdown", "柔软收尾，极简回复"


@dataclass
class MoodState:
    thread_id: str
    connection: float = 0.0
    pride: float = 0.0
    valence: float = 0.0
    arousal: float = 0.0
    immersion: float = 0.3
    last_tick_at: Optional[str] = None


# 漂移速率（每分钟）。参数从积温简化而来，先跑起来再按体感调参，
# 不追求积温原版的加速度/耦合参数表，避免过度设计。
_CONNECTION_RATE_PER_MIN = 0.01
_PRIDE_DECAY_PER_MIN = 0.003
_VALENCE_DECAY_PER_MIN = 0.005
_AROUSAL_DECAY_PER_MIN = 0.005
_IMMERSION_DECAY_PER_MIN = 0.01
_MAX_TICK_MINUTES = 240.0  # 超过 4 小时按 4 小时算，避免久别重逢时数值瞬间打满


class MoodEngine:
    """跨人格共享的状态引擎；状态以 thread_id 为粒度持久化在 SQLite。"""

    def __init__(self, db_path: str = "./data/axiodrasil_core.db"):
        self.db_path = db_path
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        # 本轮 tick 前算出的交互钩子，供 get_prompt_context 消费一次
        self._pending_hooks: Dict[str, str] = {}

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS mood_state (
                    thread_id TEXT PRIMARY KEY,
                    connection REAL NOT NULL DEFAULT 0,
                    pride REAL NOT NULL DEFAULT 0,
                    valence REAL NOT NULL DEFAULT 0,
                    arousal REAL NOT NULL DEFAULT 0,
                    immersion REAL NOT NULL DEFAULT 0.3,
                    last_tick_at TIMESTAMP
                )
                """
            )
            conn.commit()

    # ---------- 基础读写 ----------
    def _load(self, thread_id: str) -> MoodState:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                SELECT thread_id, connection, pride, valence, arousal, immersion, last_tick_at
                FROM mood_state WHERE thread_id = ?
                """,
                (thread_id,),
            )
            row = cur.fetchone()
        if row is None:
            return MoodState(thread_id=thread_id)
        return MoodState(
            thread_id=row[0],
            connection=row[1],
            pride=row[2],
            valence=row[3],
            arousal=row[4],
            immersion=row[5],
            last_tick_at=row[6],
        )

    def _save(self, state: MoodState) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO mood_state (thread_id, connection, pride, valence, arousal, immersion, last_tick_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    connection=excluded.connection,
                    pride=excluded.pride,
                    valence=excluded.valence,
                    arousal=excluded.arousal,
                    immersion=excluded.immersion,
                    last_tick_at=excluded.last_tick_at
                """,
                (
                    state.thread_id,
                    state.connection,
                    state.pride,
                    state.valence,
                    state.arousal,
                    state.immersion,
                    state.last_tick_at,
                ),
            )
            conn.commit()

    def get_state(self, thread_id: str) -> MoodState:
        return self._load(thread_id)

    def compute_interaction_hook(self, thread_id: str, now: Optional[datetime] = None) -> str:
        """在 tick 之前调用：久别 / 每日首交互提示（BIOS Module 0.4 间歇回归）。

        可通过 AX_INTERACTION_HOOKS_ENABLED=0 关闭。
        """
        if not _hooks_enabled():
            return ""
        now = now or datetime.now()
        state = self._load(thread_id)
        if not state.last_tick_at:
            return "【交互提示】本会话首次交互：简洁回应即可，不必全员欢迎或寒暄堆砌。"
        try:
            last = datetime.fromisoformat(state.last_tick_at)
        except ValueError:
            return ""
        gap_minutes = max(0.0, (now - last).total_seconds() / 60.0)
        period_key, period_label = get_period(now)
        if last.date() != now.date():
            return (
                f"【交互提示】今日首次见面（时段：{period_label}）。"
                "可按当前时段轻轻打个招呼，一句即可，不刷屏、不列清单。"
            )
        if gap_minutes >= _REUNION_GAP_MINUTES:
            return (
                "【交互提示】距上次交互已超过两小时，可自然带一句欢迎回来"
                "（如「忙完啦？」），只一句，勿重复热情堆砌。"
            )
        if period_key == "shutdown" and gap_minutes >= 30:
            return "【交互提示】已近收尾时段，语气柔和收敛，避免高能量刺激。"
        return ""

    def arm_interaction_hook(self, thread_id: str, now: Optional[datetime] = None) -> str:
        """计算并暂存本轮钩子，供随后 get_prompt_context 注入。"""
        hook = self.compute_interaction_hook(thread_id, now=now)
        if hook:
            self._pending_hooks[thread_id] = hook
        else:
            self._pending_hooks.pop(thread_id, None)
        return hook

    # ---------- 漂移 ----------
    def tick(self, thread_id: str, now: Optional[datetime] = None) -> MoodState:
        """
        推进数值漂移。用「距上次 tick 的分钟数」做时间步长；用户主动发来
        消息本身就代表"连接需求被满足"，所以漂移完成后会顺带重置 connection。
        """
        now = now or datetime.now()
        state = self._load(thread_id)

        minutes = _MAX_TICK_MINUTES
        if state.last_tick_at:
            try:
                last = datetime.fromisoformat(state.last_tick_at)
                minutes = min(max(0.0, (now - last).total_seconds() / 60.0), _MAX_TICK_MINUTES)
            except ValueError:
                pass

        period_key, _ = get_period(now)

        state.connection = _clamp(state.connection + _CONNECTION_RATE_PER_MIN * minutes, 0.0, 1.0)
        state.pride = _decay_toward_zero(state.pride, _PRIDE_DECAY_PER_MIN, minutes)
        state.valence = _decay_toward_zero(state.valence, _VALENCE_DECAY_PER_MIN, minutes)
        state.arousal = _decay_toward_zero(state.arousal, _AROUSAL_DECAY_PER_MIN, minutes)

        # focus 时段沉浸度衰减更慢（正在专注干活），free_soul/shutdown 衰减更快
        immersion_multiplier = 0.5 if period_key == "focus" else 1.5 if period_key in ("free_soul", "shutdown") else 1.0
        state.immersion = _clamp(state.immersion - _IMMERSION_DECAY_PER_MIN * immersion_multiplier * minutes, 0.0, 1.0)

        state.last_tick_at = now.isoformat()
        self._save(state)

        # 用户已经来了，连接需求部分缓解（不完全归零，模拟"见到人但话还没说完"）
        self.apply_delta(thread_id, connection=-0.35)
        return self._load(thread_id)

    def apply_pain_signal(self, thread_id: str, pain_level: int) -> MoodState:
        """把内阁已有的 pain_level（1-10）映射为 valence/arousal 的一次性扰动，
        不需要额外跑情绪分类模型。"""
        normalized = _clamp((pain_level - 1) / 9.0, 0.0, 1.0)  # 0..1
        return self.apply_delta(
            thread_id,
            valence=-normalized * 0.4,
            arousal=normalized * 0.3,
        )

    def apply_delta(
        self,
        thread_id: str,
        *,
        connection: float = 0.0,
        pride: float = 0.0,
        valence: float = 0.0,
        arousal: float = 0.0,
        immersion: float = 0.0,
    ) -> MoodState:
        state = self._load(thread_id)
        state.connection = _clamp(state.connection + connection, 0.0, 1.0)
        state.pride = _clamp(state.pride + pride, -1.0, 1.0)
        state.valence = _clamp(state.valence + valence, -1.0, 1.0)
        state.arousal = _clamp(state.arousal + arousal, -1.0, 1.0)
        state.immersion = _clamp(state.immersion + immersion, 0.0, 1.0)
        self._save(state)
        return state

    def reset_connection(self, thread_id: str) -> None:
        state = self._load(thread_id)
        state.connection = 0.0
        self._save(state)

    # ---------- 翻译成人话（喂给 LLM 的自然语言，而不是原始数值） ----------
    def get_prompt_context(self, thread_id: str, now: Optional[datetime] = None) -> str:
        state = self._load(thread_id)
        _, period_label = get_period(now)

        pieces = [f"当前时段基调：{period_label}。"]
        hook = self._pending_hooks.pop(thread_id, "")
        if hook:
            pieces.append(hook)
        elif state.connection > 0.5:
            pieces.append("陛下好一阵没怎么来找内阁说话了，惦记着但不必主动提。")
        if state.valence < -0.3 and state.arousal >= 0:
            pieces.append("最近的互动透出低落，语气里少一点欢腾。")
        elif state.valence < -0.3 and state.arousal < 0:
            pieces.append("最近的互动偏疲惫低能量，别用太亢奋的语气。")
        if state.arousal > 0.3:
            pieces.append("最近互动里带着一点焦躁/紧绷，回应节奏可以放缓。")
        if state.immersion > 0.6:
            pieces.append("陛下大概正专注在做事，非必要不打断节奏。")
        return " ".join(pieces)

    def get_style_guidance(self, thread_id: str, now: Optional[datetime] = None) -> str:
        state = self._load(thread_id)
        period_key, _ = get_period(now)

        lines: List[str] = []
        if period_key == "focus":
            lines.append("语气克制，功能优先，减少寒暄。")
        elif period_key in ("refuel", "free_soul"):
            lines.append("语气可以放松，允许闲聊式的铺垫。")
        else:
            lines.append("语气柔和收敛，避免高能量刺激。")

        if state.valence < -0.3:
            lines.append("先处理情绪，别急着讲道理或列清单。")
        if state.pride > 0.5:
            lines.append("即使想表达关心，也别表现得太明显，留一点分寸感。")
        return " ".join(lines)


__all__ = ["MoodEngine", "MoodState", "get_period"]
