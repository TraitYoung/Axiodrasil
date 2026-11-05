"""Bina 对话图：状态感知 → 回复，长期记忆由 Hindsight 提供。"""

from __future__ import annotations

from typing import NotRequired, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from infrastructure.container import get_llm, get_mood_engine
from memory.context_inject import compose_user_message
from prompts import system_prompts
from prompts.bina_context import build_bina_mode_context
from prompts.system_prompts import BINA_MEDICAL_REDLINE_BLOCK, BINA_PROMPT_TEMPLATE
from schemas.protocols import TaskIntent
from agents.solo_fast import synthesize_solo_bina_intent

MAIN_THREAD_ID = "bina-local-user"


class GraphState(TypedDict):
    current_input: str
    thread_id: str
    recent_history: list[str]
    long_term_context: str
    intent: NotRequired[TaskIntent]
    final_response: NotRequired[str]
    active_task_type: NotRequired[str]
    active_persona: NotRequired[str]


def _persona_prompt(persona: str, base_prompt: str, thread_id: str) -> str:
    """固定人格 + 动态 mood + 正/负向风格提示，跨节点共享。"""
    from prompts.steering import with_style_steering

    mood_engine = get_mood_engine()
    with_mood = system_prompts.with_mood_context(
        base_prompt,
        mood_engine.get_prompt_context(thread_id),
        mood_engine.get_style_guidance(thread_id),
    )
    return with_style_steering(with_mood, persona)


def node_solo_fast(state: GraphState):
    intent = synthesize_solo_bina_intent(state["current_input"])
    mood = get_mood_engine()
    thread_id = state["thread_id"]
    mood.arm_interaction_hook(thread_id)
    mood.tick(thread_id)
    mood.reset_connection(thread_id)
    mood.apply_pain_signal(thread_id, intent.pain_level)
    return {"intent": intent}


def node_bina(state: GraphState):
    """根据短期对话、Hindsight 记忆和当前状态回复。"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)

    mode_context, visual_rule = build_bina_mode_context(proactive=False)
    medical_block = BINA_MEDICAL_REDLINE_BLOCK if intent.pain_level > 6 else ""

    bina_prompt = _persona_prompt(
        "bina",
        BINA_PROMPT_TEMPLATE.format(
            visual_rule=visual_rule,
            medical_block=medical_block,
            mode_context=mode_context,
        ),
        thread_id,
    )

    user_status = compose_user_message(
        (
            f"陛下刚说：{intent.raw_input}\n"
            f"（内部：痛感 {intent.pain_level}/10；{mode_context}。"
            f"用短气泡接话，别写结构化安慰文，别主动给话术/热汤收尾。）"
        ),
        recent_history=state.get("recent_history", []),
        long_term_context=state.get("long_term_context", ""),
    )

    try:
        messages = [SystemMessage(content=bina_prompt), HumanMessage(content=user_status)]
        response = get_llm().invoke(messages)
        final_text = response.content
    except Exception as e:
        final_text = f"呜呜，陛下的情绪电波太强，Bina 的线路稍微短路了一下... (Error: {e})"

    # 自拍/发图：ComfyUI + 定妆 LoRA（邻舍路径）；失败不吞文本回复
    try:
        from modules.image_gen.service import maybe_attach_selfie

        final_text = maybe_attach_selfie("bina", intent.raw_input or "", str(final_text or ""))
    except Exception as exc:  # noqa: BLE001
        print(f"[image_gen] bina selfie skipped: {exc}")

    return {"final_response": final_text, "active_task_type": "emotion", "active_persona": "bina"}


workflow = StateGraph(GraphState)
workflow.add_node("solo_fast", node_solo_fast)
workflow.add_node("bina", node_bina)
workflow.set_entry_point("solo_fast")
workflow.add_edge("solo_fast", "bina")
workflow.add_edge("bina", END)
app = workflow.compile()
