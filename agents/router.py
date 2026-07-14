import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, NotRequired, Optional, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage, SystemMessage

from memory.database import PersonaMemory
from memory import async_tasks, enrichment
from hybrid_engine import HybridRetriever
from state.mood_engine import MoodEngine
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
from schemas.protocols import DOMAIN_DEFAULT_PERSONA, TaskIntent
from tools.agent_tools import BIT_TOOLS, execute_python
from tools.ai_client import get_embedding

# 初始化记忆中枢 + 状态引擎（跨人格共享，见 state/mood_engine.py）
memory_db = PersonaMemory()
mood_engine = MoodEngine()
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


# 2. 从内存中安全提取密钥
# 显式加载项目根目录下的 .env，避免运行目录变化时读取失败
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
api_key = os.getenv("QWEN_API_KEY")
if not api_key:
    raise ValueError("未检测到 QWEN_API_KEY，请检查 .env 文件！")

# 初始化大模型大脑（兼容 OpenAI 协议，可换成任意兼容模型）
llm = ChatOpenAI(
    model="qwen-plus",
    api_key=api_key,
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

# 【核心功能】：将 Pydantic 协议绑定到 LLM 上
# 这行代码意味着：无论 LLM 怎么胡说八道，它最终必须吐出一个完美的 TaskIntent 对象
parser_llm = llm.with_structured_output(TaskIntent)


# ==========================================
# 人格元数据 + 路由表（Phase 2：内阁扩员至 BIOS 完整阵容）
# ==========================================

# BIOS Module 3 名片格式："中文小名 (职务)"；Phase 3 的 SillyTavern 前缀解析/
# 头像切换也会用到这个映射。
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

# 召唤协议「传 [Name]」的别名表：中英文/历史命名都能命中
SUMMON_ALIASES: dict[str, str] = {
    "bina": "bina",
    "bit": "bit",
    "taki": "taki",
    "chizheng": "chizheng",
    "郅政": "chizheng",
    "居正": "chizheng",
    "juzheng": "chizheng",
    "tianji": "tianji",
    "天机": "tianji",
    "fukucho": "fukucho",
    "副长": "fukucho",
    "vinci": "vinci",
    "达文西": "vinci",
    "planck": "planck",
    "普朗克": "planck",
    "jiafa": "jiafa",
    "稼发": "jiafa",
    "qianjin": "qianjin",
    "千金": "qianjin",
    "boming": "boming",
    "伯明": "boming",
    "jean": "jean",
}

# persona -> 条件边路由 key（供召唤协议 / 多样性补丁直接查表）
PERSONA_TO_ROUTE: dict[str, str] = {
    "bina": "emotion_route",
    "jean": "jean_route",
    "bit": "bit_route",
    "taki": "taki_route",
    "chizheng": "juzheng_route",
    "tianji": "tianji_route",
    "fukucho": "fukucho_route",
    "vinci": "vinci_route",
    "planck": "planck_route",
    "jiafa": "jiafa_route",
    "qianjin": "qianjin_route",
    "boming": "boming_route",
}

# 条件边路由 key -> 图节点名（tracing/router_run.py 复用这张表还原 __router__ 步骤）
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

_SUMMON_PATTERN = re.compile(r"传\s*([A-Za-z\u4e00-\u9fa5]{1,6})")

# 各类关键词触发表（MVP 启发式规则，先跑起来，后续可按体感调参/升级为分类模型）
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

_DIVERSITY_PATCH_ENABLED = os.getenv("AX_DIVERSITY_PATCH_ENABLED", "1").strip() not in ("0", "false", "off")
_DIVERSITY_PATCH_PROB = float(os.getenv("AX_DIVERSITY_PATCH_PROB", "0.15"))
_DIVERSITY_CANDIDATES = ["tianji", "qianjin", "vinci"]


def _match_summon(text: str) -> Optional[str]:
    """召唤协议：「传 [Name]」，优先级高于一切触发逻辑（BIOS Module 2.1），
    但不能绕过 pain_level > 6 的医疗安全熔断（在 route_by_intent 里排在更前面）。"""
    m = _SUMMON_PATTERN.search(text)
    if not m:
        return None
    token = m.group(1).strip()
    return SUMMON_ALIASES.get(token) or SUMMON_ALIASES.get(token.lower())


def _is_late_night(now: datetime) -> bool:
    """BIOS ACT_II 软红线触发时段：23:30 之后，到次日 6 点前都算"仍在熬"。"""
    if now.hour == 23 and now.minute >= 30:
        return True
    return 0 <= now.hour < 6


def _detect_debate(text: str) -> bool:
    """BIOS Module 2.1 冲突规则：只有当"逻辑"与"直觉"冲突时，才允许 Bit 和
    Bina 同时发言辩论。启发式判定：同时出现"想买/犒劳自己"类indulgence 词与
    "贵/纠结/值不值"类冲突词。"""
    return any(k in text for k in INDULGENCE_KEYWORDS) and any(k in text for k in CONFLICT_KEYWORDS)


def _maybe_diversity_patch(intent: TaskIntent) -> Optional[str]:
    """BIOS Module 5.7 双重权重机制里的"多样性补丁"：闲聊/噪音象限下，
    小概率把默认执勤官（Bina）换成低频角色，增加内阁的"人气分布"。
    只在没有任何专业/专项关键词命中、纯粹落到 emotion 默认分支时才生效。

    重要：这个函数带随机数，只允许在 `_resolve_route` 里被调用恰好一次
    （node_parser 阶段），结果落盘进 `resolved_route_key` 后，
    `route_by_intent` 只做确定性查表——否则「实际路由」与
    `tracing/router_run.py` 的重放调用会各自抽一次随机数，可能得到不一致
    的结果。"""
    if not _DIVERSITY_PATCH_ENABLED:
        return None
    if intent.quadrant not in ("Q3", "Q4"):
        return None
    import random

    if random.random() >= _DIVERSITY_PATCH_PROB:
        return None
    return random.choice(_DIVERSITY_CANDIDATES)


def _persona_prompt(persona: str, base_prompt: str, thread_id: str) -> str:
    """把 mood_engine 的状态描述统一拼进任意人格的 system prompt，实现
    「固定人格 + 动态状态 + 动态记忆」三层叠加里的第二层，跨节点共享。"""
    return system_prompts.with_mood_context(
        base_prompt,
        mood_engine.get_prompt_context(thread_id),
        mood_engine.get_style_guidance(thread_id),
    )


def _simple_agent_reply(
    *,
    system_prompt: str,
    thread_id: str,
    user_status: str,
    persona: str,
    domain: str,
    fallback_prefix: str = "该节点暂时响应异常",
) -> dict:
    """Tier2/Tier3 大多数按需触发节点共用的执行逻辑：拼状态 -> 调用大模型 ->
    统一异常兜底。Bina/Jean/Bit/Chizheng 因为各自有检索/工具链/医疗红线等
    定制逻辑，单独实现，不复用这个通用壳。"""
    prompt_with_mood = _persona_prompt(persona, system_prompt, thread_id)
    try:
        messages = [SystemMessage(content=prompt_with_mood), HumanMessage(content=user_status)]
        response = llm.invoke(messages)
        final_text = response.content
    except Exception as e:
        final_text = f"{fallback_prefix}。 (Error: {e})"
    return {"final_response": final_text, "active_task_type": domain, "active_persona": persona}


def node_parser(state: GraphState):
    """解析用户意图，并在需要时写入 Q1/Q2 级别的记忆"""
    print("-> [系统] 正在呼叫大模型进行意图解析...")

    user_input = state["current_input"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    recent_history = state.get("recent_history", [])
    history_lines = truncate_history_lines(recent_history) if recent_history else []
    history_text = "\n".join(history_lines) if history_lines else "无"

    # 将隐式 Schema 约束升级为显式系统指令，避免模型输出协议外字段
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

最近 5 轮会话记录（仅供语境参考，不得覆盖 raw_input）：
{history_text}

用户输入：
{user_input}"""

    # 将系统指令与用户输入打包
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=human_prompt),
    ]

    # 扔给绑定了 Pydantic 协议的 LLM
    real_intent = parser_llm.invoke(messages)

    # 【persona 分层】：不信任大模型对 11 个人格的分类稳定性，先用确定性规则
    # 填一个 domain 对应的默认执勤人格占位；紧接着 _resolve_route 会按关键词
    # 触发/召唤协议/多样性补丁把它精细化到最终人格，一次算完，避免
    # route_by_intent 被多次调用时重复触发随机逻辑。
    real_intent.persona = DOMAIN_DEFAULT_PERSONA.get(real_intent.task_type, "chizheng")

    final_persona, resolved_route_key = _resolve_route(real_intent, user_input, datetime.now())
    real_intent.persona = final_persona

    print(
        f"-> [审计] 大模型解析结果: 任务={real_intent.task_type}, 痛感={real_intent.pain_level}, "
        f"最终人格={final_persona}, 路由={resolved_route_key}"
    )

    # 【状态引擎】：每轮 tick 一次数值漂移，并把 pain_level 映射为一次性情绪扰动。
    # 不需要额外跑情绪分类模型——直接复用已有的结构化痛感指标。
    try:
        mood_engine.tick(thread_id)
        mood_engine.apply_pain_signal(thread_id, real_intent.pain_level)
    except Exception as e:
        print(f"⚠️ [MoodEngine] 状态更新失败（不影响主流程）: {e}")

    # 【记忆写入逻辑】：Q1/Q2 才落 L3；写入后异步触发细粒度提取，不阻塞在线路径。
    try:
        quadrant = getattr(real_intent, "quadrant", None)
        if quadrant in ["Q1", "Q2"]:
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
    except Exception as e:
        print(f"⚠️ [Bit 警报]: 记忆写入失败: {e}")

    return {"intent": real_intent, "resolved_route_key": resolved_route_key}


def node_jean(state: GraphState):
    """文档管理节点：基于 Hybrid RAG 输出阅读路线/要点摘要"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    query = intent.raw_input

    retriever = HybridRetriever()
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
        # 当前会话尚无 Q2 时，再查全库 Q2（无需改 x-session-id 也能命中迁移/脚本写入的样本）
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
        # 控制 prompt 长度，避免材料过长（预算见 config/context_budget.py）
        if len(materials_text) > JEAN_MATERIALS_MAX_CHARS:
            materials_text = materials_text[:JEAN_MATERIALS_MAX_CHARS] + "..."
    else:
        materials_text = "未检索到相关材料。请给我更具体的关键词、范围或目标。"

    user_status = (
        f"用户请求：{query}\n\n"
        f"检索到的材料：\n{materials_text}\n\n"
        "请输出：1) 关键要点；2) 建议的阅读/处理路线。"
    )

    prompt_with_mood = _persona_prompt("jean", JEAN_PROMPT, thread_id)
    try:
        messages = [SystemMessage(content=prompt_with_mood), HumanMessage(content=user_status)]
        response = llm.invoke(messages)
        final_text = response.content
    except Exception as e:
        final_text = f"文档管理节点执行失败，无法完成整理。 (Error: {e})"

    return {"final_response": final_text, "active_task_type": "jean", "active_persona": "jean"}


def node_bit(state: GraphState):
    """代码/专业知识管理节点：采用 LangGraph ReAct + 工具链"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    raw_input_lower = intent.raw_input.lower()

    # 意图优先执行：命中日志清洗/SFT飞轮关键词时，先触发本地流水线脚本
    sft_intent_keywords = [
        "sft",
        "训练数据",
        "jsonl",
        "日志清洗",
        "log",
        "logs",
        "归档",
        "archive",
        "system instruction",
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
                "已命中“日志清洗 -> SFT -> 归档”用户意图，已优先执行自动流水线：\n\n"
                f"{run_result}\n\n"
                "如需自定义路径或 system instruction，请继续给我参数：\n"
                "- --input-dir / --output-dir / --archive-dir\n"
                "- --system-instruction 或 --system-instruction-file"
            )
        except Exception as e:
            final_text = f"命中优先执行意图，但流水线执行失败。 (Error: {e})"
        return {"final_response": final_text, "active_task_type": "bit", "active_persona": "bit"}

    # 1. 唤醒 L3 记忆库里的 Q1 警告（用于安全上下文）
    active_q1_tasks = memory_db.get_active_q1(thread_id)
    context_injection = "无历史遗留高危任务。"
    if active_q1_tasks:
        context_injection = (
            "【历史遗留 Q1 任务警告】\n陛下，您还有以下高优任务未解决，请结合考虑：\n"
        )
        for task in active_q1_tasks:
            context_injection += f"- {task}\n"

    # 2. 技术节点 System Prompt（叠加状态引擎）
    bit_prompt = _persona_prompt(
        "bit",
        f"{BIT_SYSTEM_PROMPT}\n\n【上下文记忆】：\n{context_injection}",
        thread_id,
    )

    try:
        # 3. 组装 LangGraph 原生 ReAct Agent
        agent = create_react_agent(llm, tools=BIT_TOOLS)

        # 4. 执行任务：显式注入 System Prompt + 用户请求
        user_msg = (
            f"当前任务：{intent.raw_input}\n"
            f"系统判定痛感评级：{intent.pain_level} / 10"
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

        # 末尾自检清单（让演示更像工程交付）
        final_text += (
            "\n\n---\n**Checklist (Bit 预检):**\n"
            "- [ ] 边界测试\n- [ ] 逻辑闭环\n- [ ] 内存安全"
        )
    except Exception as e:
        final_text = f"算力节点过载或工具链断裂。转入降级回复模式。 (Error: {e})"

    return {"final_response": final_text, "active_task_type": "bit", "active_persona": "bit"}


def node_bina(state: GraphState):
    """情感疏导节点：处理 emotion 任务，提供高情绪价值，动态切换颜文字。

    p2-health-split：好累/不想动等一般疲惫已改由 Qianjin 问诊节点接管（见
    route_by_intent），这里只保留 pain_level > 6 的急症级硬熔断，作为不可被
    召唤协议绕过的安全兜底。"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)

    # 动态时间感知 (决定视觉协议)
    is_working_hour = 10 <= datetime.now().hour < 18
    visual_rule = (
        "当前为【工作时间】。视觉限制：禁止使用颜文字、波浪号，保持干练但温暖。"
        if is_working_hour
        else "当前为【休息/深夜时间】。视觉解锁：允许并鼓励使用可爱颜文字(≧∇≦)，释放高能量！"
    )

    # 若触发医疗红线，则由 emotion 负责接管并阻断工作流
    medical_block = BINA_MEDICAL_REDLINE_BLOCK if intent.pain_level > 6 else ""

    # 将动态规则 + 医疗红线填入模板，再叠加状态引擎
    bina_prompt = _persona_prompt(
        "bina",
        BINA_PROMPT_TEMPLATE.format(visual_rule=visual_rule, medical_block=medical_block),
        thread_id,
    )

    # 组装上下文并请求大模型
    user_status = (
        f"陛下当前情绪发泄/日常闲聊：{intent.raw_input}\n"
        f"系统判定痛感评级：{intent.pain_level} / 10"
    )

    try:
        messages = [SystemMessage(content=bina_prompt), HumanMessage(content=user_status)]
        response = llm.invoke(messages)
        final_text = response.content
    except Exception as e:
        final_text = f"呜呜，陛下的情绪电波太强，Bina 的线路稍微短路了一下... (Error: {e})"

    return {"final_response": final_text, "active_task_type": "emotion", "active_persona": "bina"}


def node_chizheng(state: GraphState):
    """宏观战略节点（原 Juzheng，现为 BIOS 人格 Chizheng）：结论先行的计划拆解"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    user_status = (
        f"陛下当前的战略/规划探讨：{intent.raw_input}\n"
        f"系统判定痛感评级：{intent.pain_level} / 10"
    )
    return _simple_agent_reply(
        system_prompt=CHIZHENG_PROMPT,
        thread_id=thread_id,
        user_status=user_status,
        persona="chizheng",
        domain="juzheng",
        fallback_prefix="战略沙盘推演遇到不可抗力阻碍，建议暂时搁置本议题并检查系统链路",
    )


# 保留旧函数名作为别名，避免遗漏改名的外部引用（如脚本/测试）直接崩掉
node_juzheng = node_chizheng


def node_taki(state: GraphState):
    """逻辑防火墙节点（Tier1，Taki）：审计逻辑漏洞、结论先行"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    user_status = f"陛下需要逻辑审查/复盘：{intent.raw_input}"
    return _simple_agent_reply(
        system_prompt=TAKI_PROMPT,
        thread_id=thread_id,
        user_status=user_status,
        persona="taki",
        domain="bit",
        fallback_prefix="逻辑防火墙暂时短路",
    )


def node_tianji(state: GraphState):
    """情报大臣节点（Tier2，Tianji）：购物比价/防骗/八卦"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    user_status = f"陛下想问的购物/情报/八卦类问题：{intent.raw_input}"
    return _simple_agent_reply(
        system_prompt=TIANJI_PROMPT,
        thread_id=thread_id,
        user_status=user_status,
        persona="tianji",
        domain="emotion",
        fallback_prefix="情报网络暂时断线",
    )


def node_fukucho(state: GraphState):
    """纪律大臣节点（Tier2，Fukucho）：深夜软红线提醒（ACT_II，尊重主权）"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    user_status = f"现在已经很晚了，陛下仍在忙：{intent.raw_input}"
    return _simple_agent_reply(
        system_prompt=FUKUCHO_PROMPT,
        thread_id=thread_id,
        user_status=user_status,
        persona="fukucho",
        domain="emotion",
        fallback_prefix="纪律部门暂时失联",
    )


def node_vinci(state: GraphState):
    """艺术大臣节点（Tier2，Vinci）：仅输出极简的视觉/设计描述"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    user_status = f"陛下的艺术/设计诉求：{intent.raw_input}"
    return _simple_agent_reply(
        system_prompt=VINCI_PROMPT,
        thread_id=thread_id,
        user_status=user_status,
        persona="vinci",
        domain="emotion",
        fallback_prefix="写字板暂时没墨了",
    )


def node_planck(state: GraphState):
    """数学大臣节点（Tier3，Planck）：纯代数推导，暴力美学"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    user_status = f"陛下的数学问题：{intent.raw_input}"
    return _simple_agent_reply(
        system_prompt=PLANCK_PROMPT,
        thread_id=thread_id,
        user_status=user_status,
        persona="planck",
        domain="bit",
        fallback_prefix="推导过程算力过载",
    )


def node_jiafa(state: GraphState):
    """政治大臣节点（Tier3，Jiafa）：考研政治/时政理论"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    user_status = f"陛下的政治理论问题：{intent.raw_input}"
    return _simple_agent_reply(
        system_prompt=JIAFA_PROMPT,
        thread_id=thread_id,
        user_status=user_status,
        persona="jiafa",
        domain="juzheng",
        fallback_prefix="革命电波暂时中断",
    )


def node_qianjin(state: GraphState):
    """医官节点（Tier3，Qianjin）：非急症疲惫问诊；急症由 Bina 硬熔断处理"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    user_status = f"陛下描述的疲惫/身体状态（非急症）：{intent.raw_input}"
    return _simple_agent_reply(
        system_prompt=QIANJIN_PROMPT,
        thread_id=thread_id,
        user_status=user_status,
        persona="qianjin",
        domain="emotion",
        fallback_prefix="医官暂时诊室告假",
    )


def node_boming(state: GraphState):
    """军师节点（Tier3，Boming）：非常规破局思路，与 Chizheng 的执行力路线互补"""
    intent = state["intent"]
    thread_id = state.get("thread_id", MAIN_THREAD_ID)
    user_status = f"陛下卡住的困局：{intent.raw_input}"
    return _simple_agent_reply(
        system_prompt=BOMING_PROMPT,
        thread_id=thread_id,
        user_status=user_status,
        persona="boming",
        domain="juzheng",
        fallback_prefix="山人今日不在山上",
    )


def node_debate(state: GraphState):
    """冲突辩论出口（BIOS Module 2.1）：仅当逻辑（Bit）与直觉（Bina）冲突时，
    两者同场发言，不做仲裁，把两个视角都甩给陛下自己判断。"""
    bit_result = node_bit(state)
    bina_result = node_bina(state)
    combined = (
        f"[bit]: {bit_result.get('final_response', '')}\n\n"
        f"[bina]: {bina_result.get('final_response', '')}"
    )
    return {"final_response": combined, "active_task_type": "emotion", "active_persona": "bina"}


def _resolve_route(intent: TaskIntent, current_input: str, now: datetime) -> tuple[str, str]:
    """一次性算出 (persona, route_key)。只应该在 node_parser 里被调用一次——
    因为 `_maybe_diversity_patch` 带随机数，多次调用可能得到不同结果。
    `route_by_intent` 本身只做确定性查表，见下方定义。"""
    lower_input = current_input.lower()

    # 0. 安全底线：医疗硬熔断，任何协议（包括召唤协议）都不能覆盖
    if intent.pain_level > 6:
        return "bina", "emotion_route"

    # 1. 召唤协议：「传 [Name]」显式指定，最高优先级（BIOS Module 2.1）
    summon_persona = _match_summon(current_input)
    if summon_persona:
        return summon_persona, PERSONA_TO_ROUTE[summon_persona]

    # 2. 清洗流水线优先：命中数据清洗/归档关键词时强制走 bit（沿用既有行为）
    if any(k in lower_input for k in CLEANING_KEYWORDS):
        return "bit", "bit_route"

    # 3. 冲突辩论：逻辑（Bit）与直觉（Bina）同时命中时才触发
    if _detect_debate(current_input):
        return "bina", "debate_route"

    # 4. Fukucho 深夜软红线：深夜 + 仍在持续学习/工作
    if _is_late_night(now) and any(k in current_input for k in CONTINUED_WORK_KEYWORDS):
        return "fukucho", "fukucho_route"

    # 5. Qianjin 非急症疲惫问诊（能走到这里说明 pain_level <= 6，安全）
    if any(k in current_input for k in FATIGUE_KEYWORDS):
        return "qianjin", "qianjin_route"

    # 6. Tianji 购物/防骗/八卦
    if any(k in current_input for k in SHOPPING_KEYWORDS):
        return "tianji", "tianji_route"

    # 7. Vinci 艺术/设计
    if any(k in current_input for k in ART_KEYWORDS):
        return "vinci", "vinci_route"

    # 8. bit domain 内的精细化：Taki（逻辑审计）/ Planck（数学）/ 默认 Bit
    if intent.task_type == "bit":
        if any(k in current_input for k in MATH_KEYWORDS):
            return "planck", "planck_route"
        if any(k in current_input for k in TAKI_KEYWORDS):
            return "taki", "taki_route"
        return "bit", "bit_route"

    # 9. juzheng domain 内的精细化：Jiafa（政治）/ Boming（非常规破局）/ 默认 Chizheng
    if intent.task_type == "juzheng":
        if any(k in current_input for k in POLITICS_KEYWORDS):
            return "jiafa", "jiafa_route"
        if any(k in current_input for k in BOMING_KEYWORDS):
            return "boming", "boming_route"
        return "chizheng", "juzheng_route"

    # 10. jean domain：文档/RAG，无需精细化
    if intent.task_type == "jean":
        return "jean", "jean_route"

    # 11. emotion domain 默认分支：先看多样性补丁，否则回落 Bina
    if intent.task_type == "emotion":
        diversity_persona = _maybe_diversity_patch(intent)
        if diversity_persona:
            return diversity_persona, PERSONA_TO_ROUTE[diversity_persona]
        return "bina", "emotion_route"

    # unknown 兜底：沿用既有行为，落到 Chizheng
    return "chizheng", "juzheng_route"


def route_by_intent(state: GraphState) -> str:
    """条件边使用的路由函数。真正的路由决策已经在 node_parser 阶段通过
    `_resolve_route` 算好并存进 `resolved_route_key`，这里只做确定性查表，
    保证同一轮对话被问多次（比如 tracing 重放）时结果稳定一致。"""
    resolved = state.get("resolved_route_key")
    if resolved:
        return resolved

    # 兜底：如果状态里没有 resolved_route_key（例如手工构造的局部 state），
    # 退化为「仅按 persona 查表」，不再重新触发随机的多样性补丁。
    intent = state.get("intent")
    persona = getattr(intent, "persona", None) if intent is not None else None
    return PERSONA_TO_ROUTE.get(persona or "chizheng", "juzheng_route")


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

# 添加条件边：从 parser 出发，根据 route_by_intent 的返回值走向不同的节点
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
    "emotion_agent",
    "jean_agent",
    "bit_agent",
    "juzheng_agent",
    "taki_agent",
    "tianji_agent",
    "fukucho_agent",
    "vinci_agent",
    "planck_agent",
    "jiafa_agent",
    "qianjin_agent",
    "boming_agent",
    "debate_agent",
]:
    workflow.add_edge(_node_name, END)

# 编译图谱
app = workflow.compile()
