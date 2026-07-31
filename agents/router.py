"""
LangGraph 路由引擎：图状态定义 + 节点实现 + 图组装。

基础设施（LLM/记忆/状态引擎实例）从 infrastructure.container 获取，
人格元数据/路由表从 agents.persona_meta 获取，
路由决策逻辑从 agents.route_resolver 获取。
本文件只负责节点行为与图结构。
"""

from __future__ import annotations

from datetime import datetime
from typing import List, NotRequired, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent

from infrastructure.container import get_llm, get_memory_db, get_mood_engine
from memory import async_tasks, enrichment
from memory.context_inject import (
    compose_cabinet_context,
    compose_user_message,
    format_fragments_block,
    format_summaries_block,
)
from hybrid_engine import get_hybrid_retriever
from prompts import system_prompts
from prompts.system_prompts import (
    BINA_MEDICAL_REDLINE_BLOCK,
    BINA_PROMPT_TEMPLATE,
    BIT_SYSTEM_PROMPT,
    BOMING_PROMPT,
    CHIZHENG_PROMPT,
    FUKUCHO_PROMPT,
    JEAN_PROMPT,
    JIAFA_PROMPT,
    PLANCK_PROMPT,
    QIANJIN_PROMPT,
    TAKI_PROMPT,
    TIANJI_PROMPT,
    VINCI_PROMPT,
)
from config.context_budget import JEAN_MATERIALS_MAX_CHARS, truncate_history_lines
from schemas.protocols import TaskIntent
from tools.agent_tools import BIT_TOOLS, execute_python
from tools.ai_client import get_embedding

# ── 从解耦模块 re-export，保持外部引用兼容 ───────────────────────────
from agents.persona_meta import (
    DOMAIN_DEFAULT_PERSONA,
    PERSONA_META,
    PERSONA_TO_ROUTE,
    ROUTE_TO_NODE,
    SUMMON_ALIASES,
)
from agents.route_resolver import resolve_route as _resolve_route
from agents.route_resolver import route_by_intent

# 给主线任务设定一个固定的 Thread ID
MAIN_THREAD_ID = "TraitYoung_Main"


# 1. 定义状态 (State) - 相当于系统的内存条 (L1 Cache)
class GraphState(TypedDict):
    current_input: str
    thread_id: str
    recent_history: List[str]
    intent: TaskIntent
    final_response: str
    active_task_type: NotRequired[str]
    active_persona: NotRequired[str]
    # 由 node_parser 一次性算好的路由 key（见 _resolve_route），route_by_intent
    # 只做确定性查表，避免多样性补丁的随机数在「实际路由」与「tracing 重放」
    # 两次调用之间抽出不一致的结果。
    resolved_route_key: NotRequired[str]
    # 酒馆 Group Chat 强制说话人；None/缺省则走完整路由。
    forced_persona: NotRequired[str]


# 2. 通用工具函数 ───────────────────────────────────────────────────

def _persona_prompt(persona: str, base_prompt: str, thread_id: str) -> str:
    """把 mood_engine 的状态描述统一拼进任意人格的 system prompt，实现
    「固定人格 + 动态状态 + 动态记忆」三层叠加里的第二层，跨节点共享。"""
    mood_engine = get_mood_engine()
    return system_prompts.with_mood_context(
        base_prompt,
        mood_engine.get_prompt_context(thread_id),
        mood_engine.get_style_guidance(thread_id),
    )


def _memory_blocks_for_reply(
    thread_id: str,
    *,
    include_fragments: bool = False,
    persona: str = "",
) -> tuple[str, str, str]:
    """人格回复侧：L2 摘要 + 可选共享碎片 + 内阁三层（M3→M2→M1）。"""
    memory_db = get_memory_db()
    summary_block = ""
    fragment_block = ""
    cabinet_block = ""
    try:
        summary_block = format_summaries_block(memory_db, thread_id)
    except Exception as e:
        print(f"⚠️ [memory] 摘要回注失败: {e}")
    if include_fragments:
        try:
            # 共享碎片（persona 空）；人设私忆走 cabinet M2
            fragment_block = format_fragments_block(
                memory_db, thread_id, shared_only=True
            )
        except Exception as e:
            print(f"⚠️ [memory] 碎片回注失败: {e}")
    try:
        cabinet_block = compose_cabinet_context(memory_db, thread_id, persona)
    except Exception as e:
        print(f"⚠️ [memory] 内阁三层注入失败: {e}")
    return summary_block, fragment_block, cabinet_block


def _simple_agent_reply(
    *,
    state: GraphState,
    system_prompt: str,
    user_status: str,
    persona: str,
    domain: str,
    fallback_prefix: str = "该节点暂时响应异常",
    include_fragments: bool = False,
) -> dict:
    """Tier2/Tier3 大多数按需触发节点共用的执行逻辑：拼状态 -> 调用大模型 ->
    统一异常兜底。Bina/Jean/Bit/Chizheng 因为各自有检索/工具链/医疗红线等
    定制逻辑，单独实现，不复用这个通用壳。"""
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    summary_block, fragment_block, cabinet_block = _memory_blocks_for_reply(
        thread_id, include_fragments=include_fragments, persona=persona
    )
    human = compose_user_message(
        user_status,
        recent_history=state.get("recent_history", []),
        summary_block=summary_block,
        fragment_block=fragment_block,
        cabinet_block=cabinet_block,
    )
    prompt_with_mood = _persona_prompt(persona, system_prompt, thread_id)
    try:
        messages = [SystemMessage(content=prompt_with_mood), HumanMessage(content=human)]
        response = get_llm().invoke(messages)
        final_text = response.content
    except Exception as e:
        final_text = f"{fallback_prefix}。 (Error: {e})"
    return {"final_response": final_text, "active_task_type": domain, "active_persona": persona}


# 3. 节点实现 ───────────────────────────────────────────────────────

def node_parser(state: GraphState):
    """解析用户意图，并在需要时写入 Q1/Q2 级别的记忆"""
    print("-> [系统] 正在呼叫大模型进行意图解析...")

    user_input = state["current_input"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    recent_history = state.get("recent_history", [])
    history_lines = truncate_history_lines(recent_history) if recent_history else []
    history_text = "\n".join(history_lines) if history_lines else "无"

    summary_text = "无"
    try:
        summary_block = format_summaries_block(get_memory_db(), thread_id)
        if summary_block.strip():
            summary_text = summary_block
    except Exception as e:
        print(f"⚠️ [memory] parser 摘要回注失败: {e}")

    system_prompt = """你是一个任务认知路由引擎。
你必须返回合法的 JSON 结构化结果，匹配 TaskIntent 协议。

[核心分类逻辑：认知象限]
你必须分析输入并赋予 quadrant 字段以下四个值之一：
- Q1 (Critical): 包含严重生理不适、今日必须完成的死线、紧急求助。
- Q2 (Strategic): 包含长期计划、架构设计、技术笔记、深度思考。
- Q3 (Ephemeral): 包含临时琐事、非重要通知、即时但无深度的任务。
- Q4 (Noise): 包含闲聊、无意义符号、背景噪音。

[硬性规则]
1. task_type 只能是 emotion、jean、bit、juzheng、unknown 之一。
2. task_type 语义定义：
   - emotion：情绪疏导/安抚/吐槽/求支持（包含医疗红线熔断场景）。
   - jean：文档/资料管理（整理要点、阅读路线、基于检索材料的摘要）。
   - bit：代码/专业知识管理（推导、审计、给可运行代码/必要工具）。
   - juzheng：战略管理（计划、步骤拆解、复盘框架、长期安排）。
   - unknown：无法稳定判断时使用。
3. 绝对禁止输出 health_emergency 标签。严重生理风险通过 pain_level (7-10) 表达。
4. raw_input 必须原样复制。
5. urgency_level (1-5), pain_level (1-10)。
6. persona 字段不需要你判断，随便填一个合法值即可，系统会用确定性规则覆盖它。

[输出要求]
只返回 JSON 内容，不要附加解释。"""

    human_prompt = f"""请根据规则分析下面输入，并返回符合 TaskIntent 的 json。

中期会话摘要（跨窗口语境，不得覆盖 raw_input）：
{summary_text}

最近 5 轮会话记录（仅供语境参考，不得覆盖 raw_input）：
{history_text}

用户输入：
{user_input}"""

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt),
    ]

    llm = get_llm()
    parser_llm = llm.with_structured_output(TaskIntent)
    real_intent = parser_llm.invoke(messages)

    # 【persona 分层】：不信任大模型对 11 个人格的分类稳定性，先用确定性规则
    # 填一个 domain 对应的默认执勤人格占位；紧接着 _resolve_route 会按关键词
    # 触发/召唤协议/多样性补丁把它精细化到最终人格，一次算完，避免
    # route_by_intent 被多次调用时重复触发随机逻辑。
    real_intent.persona = DOMAIN_DEFAULT_PERSONA.get(real_intent.task_type, "chizheng")

    forced = (state.get("forced_persona") or "").strip() or None
    final_persona, resolved_route_key = _resolve_route(
        real_intent, user_input, datetime.now(), forced_persona=forced
    )
    real_intent.persona = final_persona

    print(
        f"-> [审计] 大模型解析结果: 任务={real_intent.task_type}, 痛感={real_intent.pain_level}, "
        f"最终人格={final_persona}, 路由={resolved_route_key}"
        + (f", 强制={forced}" if forced else "")
    )

    # 【状态引擎】：先算久别/首交互钩子，再 tick；钩子由后续人格 get_prompt_context 消费。
    try:
        mood_engine = get_mood_engine()
        mood_engine.arm_interaction_hook(thread_id)
        mood_engine.tick(thread_id)
        mood_engine.apply_pain_signal(thread_id, real_intent.pain_level)
    except Exception as e:
        print(f"⚠️ [MoodEngine] 状态更新失败（不影响主流程）: {e}")

    # 【记忆写入逻辑】：Q1/Q2 才落 L3；写入后异步触发细粒度提取 + 在线向量化。
    try:
        quadrant = getattr(real_intent, "quadrant", None)
        if quadrant in ["Q1", "Q2"]:
            memory_db = get_memory_db()
            memory_id = memory_db.save_memory(
                thread_id=thread_id,
                content=real_intent.raw_input,
                quadrant=quadrant,
            )
            print(f"📦 [归档]: 已将 {quadrant} 级别指令存入 L3 矩阵 (id={memory_id})。")
            async_tasks.schedule(
                enrichment.extract_and_store,
                thread_id=thread_id,
                source_memory_id=memory_id,
                content=real_intent.raw_input,
            )
            async_tasks.schedule(
                enrichment.embed_and_store_memory,
                memory_id=memory_id,
                content=real_intent.raw_input,
            )
    except Exception as e:
        print(f"⚠️ [Bit 警报]: 记忆写入失败: {e}")

    return {"intent": real_intent, "resolved_route_key": resolved_route_key}


def node_jean(state: GraphState):
    """文档管理节点：基于 Hybrid RAG 输出阅读路线/要点摘要"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    query = intent.raw_input

    retriever = get_hybrid_retriever()
    query_embedding = None
    try:
        query_embedding = get_embedding(query)
    except Exception as e:
        print(f"⚠️ [Jean] embedding 获取失败，退化为仅关键词召回: {e}")

    try:
        docs = retriever.search_hybrid(
            query=query,
            query_embedding=query_embedding,
            top_k=5,
            thread_id=thread_id,
            quadrant="Q2",
        )
        if not docs:
            docs = retriever.search_hybrid(
                query=query,
                query_embedding=query_embedding,
                top_k=5,
                thread_id=None,
                quadrant="Q2",
            )
    except Exception as e:
        print(f"⚠️ [Jean] hybrid 检索失败，返回空材料: {e}")
        docs = []

    if docs:
        materials_text = "\n\n".join(
            [
                f"[文献 {i + 1}] (ID: mem_{d.get('id', '')}): {d.get('content', '')}"
                for i, d in enumerate(docs)
            ]
        )
        if len(materials_text) > JEAN_MATERIALS_MAX_CHARS:
            materials_text = materials_text[:JEAN_MATERIALS_MAX_CHARS] + "..."
    else:
        materials_text = "未检索到相关材料。请给我更具体的关键词、范围或目标。"

    user_status = (
        f"用户请求：{query}\n\n"
        f"检索到的材料：\n{materials_text}\n\n"
        "请输出：1) 关键要点；2) 建议的阅读/处理路线。"
    )

    summary_block, _, cabinet_block = _memory_blocks_for_reply(
        thread_id, include_fragments=False, persona="jean"
    )
    human = compose_user_message(
        user_status,
        recent_history=state.get("recent_history", []),
        summary_block=summary_block,
        cabinet_block=cabinet_block,
    )
    prompt_with_mood = _persona_prompt("jean", JEAN_PROMPT, thread_id)
    try:
        messages = [SystemMessage(content=prompt_with_mood), HumanMessage(content=human)]
        response = get_llm().invoke(messages)
        final_text = response.content
    except Exception as e:
        final_text = f"文档管理节点执行失败，无法完成整理。 (Error: {e})"

    return {"final_response": final_text, "active_task_type": "jean", "active_persona": "jean"}


def node_bit(state: GraphState):
    """代码/专业知识管理节点：采用 LangGraph ReAct + 工具链"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    raw_input_lower = intent.raw_input.lower()

    sft_intent_keywords = [
        "sft", "训练数据", "jsonl", "日志清洗", "log", "logs", "归档", "archive", "system instruction",
    ]
    if any(k in raw_input_lower for k in sft_intent_keywords):
        pipeline_code = (
            "import subprocess\n"
            "cmd = ['python', 'tools/logs_to_sft.py', '--input-dir', 'logs', '--output-dir', 'output']\n"
            "res = subprocess.run(cmd, capture_output=True, text=True)\n"
            "print('exit_code=', res.returncode)\n"
            "print('stdout:\\n' + (res.stdout or ''))\n"
            "print('stderr:\\n' + (res.stderr or ''))\n"
        )
        try:
            run_result = execute_python.invoke({"code": pipeline_code})
            final_text = (
                '已命中「日志清洗 -> SFT -> 归档」用户意图，已优先执行自动流水线：\n\n'
                f"{run_result}\n\n"
                "如需自定义路径或 system instruction，请继续给我参数：\n"
                "- --input-dir / --output-dir / --archive-dir\n"
                "- --system-instruction 或 --system-instruction-file"
            )
        except Exception as e:
            final_text = f"命中优先执行意图，但流水线执行失败。 (Error: {e})"
        return {"final_response": final_text, "active_task_type": "bit", "active_persona": "bit"}

    memory_db = get_memory_db()
    active_q1_tasks = memory_db.get_active_q1(thread_id)
    context_injection = "无历史遗留高危任务。"
    if active_q1_tasks:
        context_injection = (
            "【历史遗留 Q1 任务警告】\n陛下，您还有以下高优任务未解决，请结合考虑：\n"
        )
        for task in active_q1_tasks:
            context_injection += f"- {task}\n"

    bit_prompt = _persona_prompt(
        "bit",
        f"{BIT_SYSTEM_PROMPT}\n\n【上下文记忆】：\n{context_injection}",
        thread_id,
    )

    try:
        agent = create_react_agent(get_llm(), tools=BIT_TOOLS)
        summary_block, _, cabinet_block = _memory_blocks_for_reply(
            thread_id, include_fragments=False, persona="bit"
        )
        user_msg = compose_user_message(
            (
                f"当前任务：{intent.raw_input}\n"
                f"系统判定痛感评级：{intent.pain_level} / 10"
            ),
            recent_history=state.get("recent_history", []),
            summary_block=summary_block,
            cabinet_block=cabinet_block,
        )
        result = agent.invoke(
            {
                "messages": [
                    SystemMessage(content=bit_prompt),
                    HumanMessage(content=user_msg),
                ]
            }
        )
        final_text = result["messages"][-1].content
        final_text += (
            "\n\n---\n**Checklist (Bit 预检):**\n"
            "- [ ] 边界测试\n- [ ] 逻辑闭环\n- [ ] 内存安全"
        )
    except Exception as e:
        final_text = f"算力节点过载或工具链断裂。转入降级回复模式。 (Error: {e})"

    return {"final_response": final_text, "active_task_type": "bit", "active_persona": "bit"}


def node_bina(state: GraphState):
    """情感疏导节点：处理 emotion 任务，提供高情绪价值，动态切换颜文字。

    p2-health-split：好累/不想动等一般疲惫已改由 Qianjin 问诊节点接管，
    这里只保留 pain_level > 6 的急症级硬熔断。"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)

    hour = datetime.now().hour
    is_working_hour = 10 <= hour < 18
    visual_rule = (
        "当前为【工作时间】。视觉限制：禁止使用颜文字、波浪号，保持干练但温暖。"
        if is_working_hour
        else "当前为【休息/深夜时间】。视觉解锁：允许并鼓励使用可爱颜文字(≧∇≦)，释放高能量！"
    )
    if 8 <= hour < 10:
        mode_context = "单人密谈 · 晨间温和启动：自然唤醒，可给轻量生活提案，勿盘问进度。"
    elif 12 <= hour < 14:
        mode_context = "单人密谈 · 午餐闲聊：允许吐槽与八卦，优先情绪价值。"
    elif 18 <= hour < 23:
        mode_context = "单人密谈 · 晚间家庭模式：娱乐豁免，禁止把话题硬拽回学习 KPI。"
    elif hour >= 23 or hour < 8:
        mode_context = "单人密谈 · 深夜收尾：短回复、柔软陪伴；若陛下仍在硬肝，只给一次轻提醒。"
    else:
        mode_context = "单人密谈 · 日间陪伴：干练但亲密；先接住状态，再给够用的下一步。"

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

    summary_block, fragment_block, cabinet_block = _memory_blocks_for_reply(
        thread_id, include_fragments=True, persona="bina"
    )
    user_status = compose_user_message(
        (
            f"陛下当前情绪发泄/日常闲聊：{intent.raw_input}\n"
            f"系统判定痛感评级：{intent.pain_level} / 10\n"
            f"对话模式：{mode_context}"
        ),
        recent_history=state.get("recent_history", []),
        summary_block=summary_block,
        fragment_block=fragment_block,
        cabinet_block=cabinet_block,
    )

    try:
        messages = [SystemMessage(content=bina_prompt), HumanMessage(content=user_status)]
        response = get_llm().invoke(messages)
        final_text = response.content
    except Exception as e:
        final_text = f"呜呜，陛下的情绪电波太强，Bina 的线路稍微短路了一下... (Error: {e})"

    return {"final_response": final_text, "active_task_type": "emotion", "active_persona": "bina"}


def node_chizheng(state: GraphState):
    """宏观战略节点（原 Juzheng，现为 BIOS 人格 Chizheng）：结论先行的计划拆解"""
    intent = state["intent"]
    user_status = (
        f"陛下当前的战略/规划探讨：{intent.raw_input}\n"
        f"系统判定痛感评级：{intent.pain_level} / 10"
    )
    return _simple_agent_reply(
        state=state,
        system_prompt=CHIZHENG_PROMPT,
        user_status=user_status,
        persona="chizheng",
        domain="juzheng",
        fallback_prefix="战略沙盘推演遇到不可抗力阻碍，建议暂时搁置本议题并检查系统链路",
    )


# 保留旧函数名作为别名，避免遗漏改名的外部引用
node_juzheng = node_chizheng


def node_taki(state: GraphState):
    """逻辑防火墙节点（Tier1，Taki）：审计逻辑漏洞、结论先行"""
    intent = state["intent"]
    user_status = f"陛下需要逻辑审查/复盘：{intent.raw_input}"
    return _simple_agent_reply(
        state=state,
        system_prompt=TAKI_PROMPT,
        user_status=user_status,
        persona="taki",
        domain="bit",
        fallback_prefix="逻辑防火墙暂时短路",
    )


def node_tianji(state: GraphState):
    """情报大臣节点（Tier2，Tianji）：购物比价/防骗/八卦"""
    intent = state["intent"]
    user_status = f"陛下想问的购物/情报/八卦类问题：{intent.raw_input}"
    return _simple_agent_reply(
        state=state,
        system_prompt=TIANJI_PROMPT,
        user_status=user_status,
        persona="tianji",
        domain="emotion",
        fallback_prefix="情报网络暂时断线",
        include_fragments=True,
    )


def node_fukucho(state: GraphState):
    """纪律大臣节点（Tier2，Fukucho）：深夜软红线提醒（ACT_II，尊重主权）"""
    intent = state["intent"]
    user_status = f"现在已经很晚了，陛下仍在忙：{intent.raw_input}"
    return _simple_agent_reply(
        state=state,
        system_prompt=FUKUCHO_PROMPT,
        user_status=user_status,
        persona="fukucho",
        domain="emotion",
        fallback_prefix="纪律部门暂时失联",
        include_fragments=True,
    )


def node_vinci(state: GraphState):
    """艺术大臣节点（Tier2，Vinci）：仅输出极简的视觉/设计描述"""
    intent = state["intent"]
    user_status = f"陛下的艺术/设计诉求：{intent.raw_input}"
    return _simple_agent_reply(
        state=state,
        system_prompt=VINCI_PROMPT,
        user_status=user_status,
        persona="vinci",
        domain="emotion",
        fallback_prefix="写字板暂时没墨了",
    )


def node_planck(state: GraphState):
    """数学大臣节点（Tier3，Planck）：纯代数推导，暴力美学"""
    intent = state["intent"]
    user_status = f"陛下的数学问题：{intent.raw_input}"
    return _simple_agent_reply(
        state=state,
        system_prompt=PLANCK_PROMPT,
        user_status=user_status,
        persona="planck",
        domain="bit",
        fallback_prefix="推导过程算力过载",
    )


def node_jiafa(state: GraphState):
    """政治大臣节点（Tier3，Jiafa）：考研政治/时政理论"""
    intent = state["intent"]
    user_status = f"陛下的政治理论问题：{intent.raw_input}"
    return _simple_agent_reply(
        state=state,
        system_prompt=JIAFA_PROMPT,
        user_status=user_status,
        persona="jiafa",
        domain="juzheng",
        fallback_prefix="革命电波暂时中断",
    )


def node_qianjin(state: GraphState):
    """医官节点（Tier3，Qianjin）：非急症疲惫问诊；急症由 Bina 硬熔断处理"""
    intent = state["intent"]
    user_status = f"陛下描述的疲惫/身体状态（非急症）：{intent.raw_input}"
    return _simple_agent_reply(
        state=state,
        system_prompt=QIANJIN_PROMPT,
        user_status=user_status,
        persona="qianjin",
        domain="emotion",
        fallback_prefix="医官暂时诊室告假",
        include_fragments=True,
    )


def node_boming(state: GraphState):
    """军师节点（Tier3，Boming）：非常规破局思路"""
    intent = state["intent"]
    user_status = f"陛下卡住的困局：{intent.raw_input}"
    return _simple_agent_reply(
        state=state,
        system_prompt=BOMING_PROMPT,
        user_status=user_status,
        persona="boming",
        domain="juzheng",
        fallback_prefix="山人今日不在山上",
    )


def node_debate(state: GraphState):
    """冲突辩论出口（BIOS Module 2.1）：Bit 与 Bina 并行发言。"""
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=2) as pool:
        bit_future = pool.submit(node_bit, state)
        bina_future = pool.submit(node_bina, state)
        bit_result = bit_future.result()
        bina_result = bina_future.result()

    combined = (
        f"[bit]: {bit_result.get('final_response', '')}\n\n"
        f"[bina]: {bina_result.get('final_response', '')}"
    )
    return {"final_response": combined, "active_task_type": "emotion", "active_persona": "bina"}


# 4. 构建图 (Build the Graph)
workflow = StateGraph(GraphState)

workflow.add_node("parser", node_parser)
workflow.add_node("emotion_agent", node_bina)
workflow.add_node("jean_agent", node_jean)
workflow.add_node("bit_agent", node_bit)
workflow.add_node("juzheng_agent", node_chizheng)
workflow.add_node("taki_agent", node_taki)
workflow.add_node("tianji_agent", node_tianji)
workflow.add_node("fukucho_agent", node_fukucho)
workflow.add_node("vinci_agent", node_vinci)
workflow.add_node("planck_agent", node_planck)
workflow.add_node("jiafa_agent", node_jiafa)
workflow.add_node("qianjin_agent", node_qianjin)
workflow.add_node("boming_agent", node_boming)
workflow.add_node("debate_agent", node_debate)

workflow.set_entry_point("parser")

workflow.add_conditional_edges(
    "parser",
    route_by_intent,
    {
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
    },
)

for _node_name in [
    "emotion_agent", "jean_agent", "bit_agent", "juzheng_agent",
    "taki_agent", "tianji_agent", "fukucho_agent", "vinci_agent",
    "planck_agent", "jiafa_agent", "qianjin_agent", "boming_agent",
    "debate_agent",
]:
    workflow.add_edge(_node_name, END)

app = workflow.compile()
