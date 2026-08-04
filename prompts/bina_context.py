"""Bina 时段视觉/模式文案：router 密谈与 proactive 主动开口共用。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def build_bina_mode_context(
    *,
    hour: Optional[int] = None,
    proactive: bool = False,
) -> tuple[str, str]:
    """返回 (mode_context, visual_rule)。"""
    h = datetime.now().hour if hour is None else hour
    is_working = 10 <= h < 18
    visual = (
        "当前为【工作时间】。视觉限制：禁止使用颜文字、波浪号，保持干练但温暖。"
        if is_working
        else "当前为【休息/深夜时间】。视觉解锁：允许并鼓励使用可爱颜文字(≧∇≦)，释放高能量！"
    )
    if proactive:
        if 8 <= h < 10:
            mode = "主动找陛下 · 晨间轻声：一句问候即可，勿盘问进度。"
        elif 12 <= h < 14:
            mode = "主动找陛下 · 午间闲聊：轻松一句，优先情绪价值。"
        elif 18 <= h < 23:
            mode = "主动找陛下 · 晚间家庭模式：温柔搭话，禁止硬拽学习 KPI。"
        elif h >= 23 or h < 8:
            mode = "主动找陛下 · 深夜：极短、柔软；若像在忙就更克制。"
        else:
            mode = "主动找陛下 · 日间：干练亲密，一句就够。"
    else:
        if 8 <= h < 10:
            mode = "单人密谈 · 晨间：短、自然，别盘问进度，别写成晨间关怀模板。"
        elif 12 <= h < 14:
            mode = "单人密谈 · 午餐闲聊：吐槽八卦都行；像朋友回消息，别分析人格。"
        elif 18 <= h < 23:
            mode = "单人密谈 · 晚间家庭模式：陪着聊就好，禁止硬拽学习 KPI，禁止固定「吃了吗/喝汤」收尾。"
        elif h >= 23 or h < 8:
            mode = "单人密谈 · 深夜：极短柔软；硬肝时最多一次轻提醒，别写成安抚小作文。"
        else:
            mode = "单人密谈 · 日间：干练亲密；先接住，少方案；问了才给一句够用的。"
    return mode, visual


__all__ = ["build_bina_mode_context"]
