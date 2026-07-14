"""
AI 赋能软件工程流水线：多步编排 + 敏捷/教材式产物（每步只依赖上一步 JSON，省 Token）。

对齐常见软件工程课与敏捷实践：用户故事、Sprint 目标、待办排序、DoD、CHANGELOG、短回顾。
不入主 LangGraph，避免无谓 parser 调用；由 main 直接调度。
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from config.context_budget import (
    WORKFLOW_STEP_JSON_MAX_CHARS,
    WORKFLOW_USER_TEXT_MAX_CHARS,
    clip_text,
)
from schemas.workflows import (
    DevCodeSketch,
    DevOutline,
    DevTaskSpec,
    DevTestsChangelog,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _step(
    idx: int,
    node: str,
    t_prev: float,
    summary: Dict[str, Any],
) -> Tuple[Dict[str, Any], float]:
    t_now = time.perf_counter()
    duration_ms = round((t_now - t_prev) * 1000, 2)
    return (
        {
            "index": idx,
            "node": node,
            "ts": _now_iso(),
            "duration_ms": duration_ms,
            "keys_written": [],
            "summary": summary,
        },
        t_now,
    )


def _json_clip(obj: Any) -> str:
    s = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    return clip_text(s, WORKFLOW_STEP_JSON_MAX_CHARS)


def run_dev_pipeline(user_text: str, llm) -> Tuple[str, List[Dict[str, Any]]]:
    """
    四步（对应「需求 → 规划与设计 → 实现草案 → 测试与交付闭环」）：
    1. 需求发现（用户故事、验收标准、MVP Sprint 目标）
    2. Sprint 待办与架构（有序 backlog、Parking lot、Spike）
    3. 实现草案（代码草图）
    4. 测试、DoD、CHANGELOG、CI 提示、Sprint 回顾一句
    """
    clipped = clip_text(user_text.strip(), WORKFLOW_USER_TEXT_MAX_CHARS)
    steps: List[Dict[str, Any]] = []
    t_prev = time.perf_counter()

    spec_llm = llm.with_structured_output(DevTaskSpec)
    spec = spec_llm.invoke(
        [
            SystemMessage(
                content=(
                    "你是结合软件工程规范与敏捷实践的「需求教练」。"
                    "只根据用户原文抽取结构化结果，填满 DevTaskSpec 各字段。\n"
                    "- goal：业务目标一句话 + 必要背景（勿空泛）。\n"
                    "- acceptance_criteria：可测试、可验收的条件（类似教材中的验收标准）。\n"
                    "- user_stories：3～6 条，尽量 As a … I want … so that …；若信息不足则写「待澄清」占位 + 假设。\n"
                    "- mvp_sprint_goal：本迭代能交付的最小增量（对标 Sprint Goal）。\n"
                    "- measurable_outcomes：可观察结果或指标（不必量化到数字也可写「可演示 / 可跑通」）。\n"
                    "不要复述长文；constraints / stack_hint 保持简短。"
                )
            ),
            HumanMessage(content=f"产品负责人原始描述：\n{clipped}"),
        ]
    )
    s1, t_prev = _step(1, "workflow.se.discovery", t_prev, {"discovery": spec.model_dump()})
    steps.append(s1)

    outline_llm = llm.with_structured_output(DevOutline)
    spec_json = _json_clip(spec.model_dump())
    outline = outline_llm.invoke(
        [
            SystemMessage(
                content=(
                    "你是 Tech Lead + Scrum Master。只依据上一份 JSON（需求与故事），产出 DevOutline。\n"
                    "- modules / data_flow / risks：架构级拆分与数据流、主要风险。\n"
                    "- backlog_mvp_ordered：本 Sprint 内**按实现顺序**排列的具体任务（颗粒度到 0.5～2 天可完成项）。\n"
                    "- backlog_parking_lot：明确推迟到后续迭代的条目。\n"
                    "- technical_spikes：必须先做试验才能估点的技术探针。\n"
                    "不要索要更多用户原文；信息缺口写入 risks 或 Parking lot。"
                )
            ),
            HumanMessage(content=f"需求与故事 JSON：\n{spec_json}"),
        ]
    )
    s2, t_prev = _step(2, "workflow.se.sprint_design", t_prev, {"sprint_design": outline.model_dump()})
    steps.append(s2)

    code_llm = llm.with_structured_output(DevCodeSketch)
    bundle = _json_clip({"discovery": spec.model_dump(), "sprint_design": outline.model_dump()})
    sketch = code_llm.invoke(
        [
            SystemMessage(
                content=(
                    "你是实现工程师。只收到 discovery+sprint_design 的 JSON。"
                    "请给出**单文件或清晰分区的代码草稿**，体现 MVP 的第一条或前两条 backlog 的核心路径；"
                    "language 标明语言；notes 写依赖、环境、后续重构点。不要粘贴整份 JSON。"
                )
            ),
            HumanMessage(content=f"上下文 JSON：\n{bundle}"),
        ]
    )
    s3, t_prev = _step(3, "workflow.se.implementation_sketch", t_prev, {"sketch": sketch.model_dump()})
    steps.append(s3)

    tc_llm = llm.with_structured_output(DevTestsChangelog)
    bundle2 = _json_clip(
        {
            "discovery": spec.model_dump(),
            "sprint_design": outline.model_dump(),
            "sketch": sketch.model_dump(),
        }
    )
    delivery = tc_llm.invoke(
        [
            SystemMessage(
                content=(
                    "你是 QA + 发布协调。基于 JSON（需求、待办、代码草稿）填写 DevTestsChangelog。\n"
                    "- test_cases：可自动化或手测的用例标题级列表。\n"
                    "- definition_of_done：本增量合入主干的 DoD 检查项（对齐敏捷「完成定义」）。\n"
                    "- ci_cd_notes：流水线、lint、构建、环境变量等可执行提示。\n"
                    "- changelog_entry：面向同事的 CHANGELOG 条目（含 Breaking/Added/Fixed 语气之一即可）。\n"
                    "- sprint_retrospective_one_liner：一句回顾（例如「下次先补契约测试」）。"
                )
            ),
            HumanMessage(content=f"上下文 JSON：\n{bundle2}"),
        ]
    )
    s4, t_prev = _step(4, "workflow.se.delivery_review", t_prev, {"delivery": delivery.model_dump()})
    steps.append(s4)

    final = (
        "## AI 赋能软件工程流水线（敏捷取向 · 多步编排）\n\n"
        "> 将教材中的需求、迭代、DoD、回顾等实践压缩为多步结构化产出；"
        "后几步只携带上一步 JSON 摘要，控制上下文体积。\n\n"
        "### 1) 需求发现 · 用户故事与 Sprint 目标\n"
        f"{json.dumps(spec.model_dump(), ensure_ascii=False, indent=2)}\n\n"
        "### 2) Sprint 待办与架构 / 数据流\n"
        f"{json.dumps(outline.model_dump(), ensure_ascii=False, indent=2)}\n\n"
        "### 3) 实现草案（MVP 路径）\n"
        f"```{sketch.language}\n{sketch.code}\n```\n"
        f"{sketch.notes}\n\n"
        "### 4) 测试 · DoD · CHANGELOG · CI · 回顾\n"
        f"{json.dumps(delivery.model_dump(), ensure_ascii=False, indent=2)}\n"
    )
    for i, st in enumerate(steps, start=1):
        st["index"] = i
    return final, steps


def synthetic_intent_for_workflow(
    raw_input: str,
    *,
    task_type: str = "bit",
) -> Any:
    """生成合法 TaskIntent，供 ChatResponse 与前端兼容。"""
    from typing import Literal, cast

    from schemas.protocols import TaskIntent

    clip = clip_text(raw_input.strip(), 12000)
    tt = cast(Literal["emotion", "jean", "bit", "juzheng", "unknown"], task_type)
    return TaskIntent(
        task_type=tt,
        urgency_level=2,
        pain_level=1,
        raw_input=clip or ".",
        quadrant="Q3",
    )
