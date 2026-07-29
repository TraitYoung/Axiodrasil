from uuid import uuid4
import hashlib
import re
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import FastAPI, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.persona_meta import PERSONA_META, PERSONA_TO_ROUTE, SUMMON_ALIASES
from agents.router import app as router_graph
from agents.workflow_pipelines import run_dev_pipeline, synthetic_intent_for_workflow
from infrastructure.container import get_chat_model, get_llm, get_llm_provider, get_memory_db
from memory import async_tasks
from memory.cabinet_layers import (
    append_debate_exchange,
    close_and_compress,
    detect_consensus_close,
    extract_persona_private,
)
from memory.session_cache import SessionCache
from memory.summary_service import maybe_trigger_rolling_summary
from schemas.protocols import TaskIntent
from schemas.trace import TraceStep
from tracing.router_run import run_router_traced

app = FastAPI(title="Axiodrasil Core API", version="1.0.0")

session_cache = SessionCache(ttl_seconds=3600, window_size=5)

# Host 接口矩阵：装配适配器并挂载功能模块路由（personas catalog 等）
try:
    from app.registry import bootstrap_registry, get_registry
    from modules.personas.routes import router as personas_router

    bootstrap_registry()
    app.state.matrix = get_registry()  # type: ignore[attr-defined]
    app.include_router(personas_router)
except Exception as _matrix_exc:  # pragma: no cover
    print(f"⚠️ [host] 接口矩阵装配失败: {_matrix_exc}")

_AX_PERSONA_TAG_RE = re.compile(r"\[AX_PERSONA:([a-zA-Z]+)\]", re.IGNORECASE)
_MODEL_PERSONA_RE = re.compile(
    r"^(?:axiodrasil[-_])?([a-zA-Z]+)$", re.IGNORECASE
)


def _normalize_persona(token: Optional[str]) -> Optional[str]:
    if not token or not str(token).strip():
        return None
    raw = str(token).strip()
    mapped = SUMMON_ALIASES.get(raw) or SUMMON_ALIASES.get(raw.lower())
    if mapped and mapped in PERSONA_TO_ROUTE:
        return mapped
    return None


def _persona_from_model(model: str) -> Optional[str]:
    if not model:
        return None
    m = _MODEL_PERSONA_RE.match(model.strip())
    if not m:
        return None
    return _normalize_persona(m.group(1))


def _persona_from_messages(messages: list) -> Optional[str]:
    for msg in messages:
        content = getattr(msg, "content", None) or ""
        hit = _AX_PERSONA_TAG_RE.search(content)
        if hit:
            found = _normalize_persona(hit.group(1))
            if found:
                return found
    return None


def _resolve_forced_persona(
    *,
    x_persona: Optional[str],
    model: Optional[str],
    messages: Optional[list],
) -> Optional[str]:
    """优先级：x-persona 头 > model id > messages 内 [AX_PERSONA:id]。"""
    return (
        _normalize_persona(x_persona)
        or _persona_from_model(model or "")
        or _persona_from_messages(messages or [])
    )


def _load_recent_history(session_id: str, limit: int = 5) -> list[str]:
    """优先 Redis 热窗；空或失败时回退 SQLite 持久 turn。"""
    try:
        lines = session_cache.format_recent_history(session_id=session_id, limit=limit)
        if lines:
            return lines
    except Exception:
        pass
    try:
        return get_memory_db().format_chat_history(session_id, limit=limit)
    except Exception:
        return []


def _persist_turn(session_id: str, user_text: str, assistant_text: str) -> None:
    """双写：Redis 热缓存 + SQLite 冷历史（互不影响失败）。"""
    try:
        session_cache.append_turn(
            session_id=session_id,
            user_text=user_text,
            assistant_text=assistant_text,
        )
    except Exception:
        pass
    try:
        get_memory_db().append_chat_turn(session_id, user_text, assistant_text)
    except Exception as e:
        print(f"⚠️ [chat-persist] SQLite 写 turn 失败: {e}")


def _load_history_turns(session_id: str, limit: int = 50) -> list[dict]:
    """history/export：优先持久层；若无记录再试 Redis。"""
    try:
        turns = get_memory_db().get_chat_turns(session_id, limit=limit)
        if turns:
            return turns
    except Exception as e:
        print(f"⚠️ [chat-history] SQLite 读失败: {e}")
    try:
        return session_cache.get_recent_turns(session_id=session_id, limit=limit)
    except Exception:
        return []


@app.get("/api/v1/health")
def api_health():
    """轻量探活：供 Next 开发代理与运维脚本探测；不调用大模型。"""
    redis_ok = False
    try:
        session_cache.client.ping()
        redis_ok = True
    except Exception:
        pass
    return {
        "ok": True,
        "redis": redis_ok,
        "llm_provider": get_llm_provider(),
        "chat_model": get_chat_model(),
    }


WorkflowMode = Literal["default", "dev_pipeline"]


class ChatRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=12000, description="用户原始输入")
    workflow_mode: WorkflowMode = Field(
        default="default",
        description="default=内阁路由；dev_pipeline=AI 赋能软件工程（敏捷取向）多步流水线",
    )
    forced_persona: Optional[str] = Field(
        default=None,
        description="强制本轮说话人设（酒馆 Group Chat）；仍受 pain_level>6 医疗熔断约束",
    )
    strip_persona_prefix: bool = Field(
        default=False,
        description="True 时对外回复去掉 [persona]: 前缀（Group Chat 气泡已有角色名）",
    )


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    intent: TaskIntent
    trace_id: str
    trace: list[TraceStep]
    active_persona: str = Field(default="", description="本轮实际执勤人格（11 人 BIOS 阵容 + Jean）")


class ChatExportItem(BaseModel):
    user: str
    assistant: str
    ts: str


class ChatExportResponse(BaseModel):
    session_id: str
    turns: List[ChatExportItem]
    file_path: str


class ChatHistoryResponse(BaseModel):
    session_id: str
    turns: List[ChatExportItem]


def _execute_turn(payload: ChatRequest, session_id: str) -> tuple[str, TaskIntent, list, str, str]:
    """
    执行一轮对话或工作流。返回 (reply, intent, trace_raw, active_task_type, active_persona)。

    默认 reply 带 `[persona]:` 前缀；`strip_persona_prefix=True`（Group Chat）时对外去前缀，
    调用方应用带前缀文本写回记忆。
    """
    if payload.workflow_mode == "dev_pipeline":
        reply_raw, trace_raw = run_dev_pipeline(payload.text, get_llm())
        intent = synthetic_intent_for_workflow(payload.text, task_type="bit")
        active_task_type = "dev_pipeline"
        active_persona = "bit"
    else:
        recent_history = _load_recent_history(session_id, limit=5)
        graph_state = {
            "current_input": payload.text,
            "thread_id": session_id,
            "recent_history": recent_history,
        }
        forced = _normalize_persona(payload.forced_persona)
        if forced:
            graph_state["forced_persona"] = forced
        result, trace_raw = run_router_traced(router_graph, graph_state)
        reply_raw = str(result.get("final_response", ""))
        intent = result.get("intent")
        if intent is None:
            raise HTTPException(status_code=500, detail="router returned empty intent")
        active_task_type = result.get("active_task_type")
        if active_task_type is None:
            active_task_type = getattr(intent, "task_type", None)
        active_persona = result.get("active_persona") or getattr(intent, "persona", None)

    prefix_map = {
        "emotion": "bina",
        "jean": "jean",
        "bit": "bit",
        "juzheng": "juzheng",
        "unknown": "juzheng",
        "dev_pipeline": "dev",
    }
    prefix = str(active_persona) if active_persona else prefix_map.get(str(active_task_type), "juzheng")
    reply_clean = re.sub(r"^\s*\[[^\]]+]\s*[:：]\s*", "", str(reply_raw))
    reply_labeled = f"[{prefix}]: {reply_clean}"
    reply_out = reply_clean if payload.strip_persona_prefix else reply_labeled
    return reply_out, intent, trace_raw, str(active_task_type), str(active_persona or prefix)


def _after_turn_memory(
    session_id: str,
    user_text: str,
    reply_for_client: str,
    active_persona: str,
    *,
    group_mode: bool,
) -> str:
    """写回 L1、可选 M1/M2，并在散会口令时压缩进 M3。返回可能带前缀的持久化文本。"""
    labeled = reply_for_client
    if not re.match(r"^\s*\[[^\]]+]\s*[:：]", reply_for_client or ""):
        labeled = f"[{active_persona}]: {reply_for_client}"

    _persist_turn(session_id, user_text, labeled)
    maybe_trigger_rolling_summary(session_id, session_cache, get_memory_db())

    if group_mode and active_persona:
        try:
            append_debate_exchange(
                session_id,
                user_text=user_text,
                assistant_text=re.sub(
                    r"^\s*\[[^\]]+]\s*[:：]\s*", "", labeled
                ),
                persona=active_persona,
            )
        except Exception as e:
            print(f"⚠️ [cabinet] M1 写回失败: {e}")
        try:
            async_tasks.schedule(
                extract_persona_private,
                session_id,
                active_persona,
                user_text=user_text,
                assistant_text=re.sub(r"^\s*\[[^\]]+]\s*[:：]\s*", "", labeled),
            )
        except Exception as e:
            print(f"⚠️ [cabinet] M2 私忆调度失败: {e}")

    if detect_consensus_close(user_text) or detect_consensus_close(reply_for_client):
        try:
            summary = close_and_compress(session_id)
            if summary:
                print(f"📜 [cabinet] 已散会并写入共识: {summary[:80]}...")
        except Exception as e:
            print(f"⚠️ [cabinet] 共识压缩失败: {e}")

    return labeled


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_api(
    payload: ChatRequest,
    response: Response,
    x_session_id: str | None = Header(default=None),
    x_trace_id: str | None = Header(default=None, alias="x-trace-id"),
):
    session_id = x_session_id or str(uuid4())
    trace_id = (x_trace_id or "").strip() or str(uuid4())
    response.headers["X-Trace-Id"] = trace_id

    try:
        reply, intent, trace_raw, _active, active_persona = _execute_turn(payload, session_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"turn failed: {exc}") from exc

    _after_turn_memory(
        session_id,
        payload.text,
        reply,
        active_persona,
        group_mode=bool(payload.forced_persona),
    )

    trace = [TraceStep.model_validate(s) for s in trace_raw]
    return ChatResponse(
        session_id=session_id,
        reply=reply,
        intent=intent,
        trace_id=trace_id,
        trace=trace,
        active_persona=active_persona,
    )


@app.post("/api/v1/chat/stream")
async def chat_stream_api(
    payload: ChatRequest,
    x_session_id: str | None = Header(default=None),
    x_trace_id: str | None = Header(default=None, alias="x-trace-id"),
):
    """
    SSE 流式输出接口：返回 text/event-stream。
    说明：本实现先走一次 router 生成完整回复，然后把 reply 按片段分批吐给前端。
    这样可以不破坏现有 LangGraph 逻辑，同时让前端获得“打字机效果”的流式体验。
    """
    session_id = x_session_id or str(uuid4())
    trace_id = (x_trace_id or "").strip() or str(uuid4())

    try:
        reply, intent, trace_raw, _active, active_persona = _execute_turn(payload, session_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"turn failed: {exc}") from exc

    _after_turn_memory(
        session_id,
        payload.text,
        reply,
        active_persona,
        group_mode=bool(payload.forced_persona),
    )

    trace_payload = [TraceStep.model_validate(s).model_dump() for s in trace_raw]

    async def event_gen():
        # 1) meta（含全链路追踪，便于前端展示）
        meta = {
            "session_id": session_id,
            "intent": intent.model_dump(),
            "trace_id": trace_id,
            "trace": trace_payload,
            "workflow_mode": payload.workflow_mode,
            "active_persona": active_persona,
        }
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

        # 2) content chunks (pseudo streaming)
        chunk_size = 12
        for i in range(0, len(reply), chunk_size):
            piece = reply[i : i + chunk_size]
            data = {"type": "delta", "content": piece}
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)

        # 3) done
        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"X-Trace-Id": trace_id},
    )


@app.post("/api/v1/chat/export", response_model=ChatExportResponse)
async def chat_export_api(x_session_id: str | None = Header(default=None), limit: int = 20):
    """
    导出当前 session 的最近对话轮次到 output/chats/*.jsonl。

    - 文件命名：YYYYMMDD_HHMMSS_首句prompt截断.jsonl
    - 内容：每行一个 {user, assistant, ts}
    """
    if not x_session_id:
        raise HTTPException(status_code=400, detail="missing x-session-id header")

    turns = _load_history_turns(x_session_id, limit=limit)
    if not turns:
        raise HTTPException(status_code=404, detail="no turns found for this session")

    project_root = Path(__file__).resolve().parent
    export_dir = project_root / "output" / "chats"
    export_dir.mkdir(parents=True, exist_ok=True)

    first_user = ""
    for t in turns:
        if t.get("user"):
            first_user = t["user"]
            break
    title = (first_user.splitlines()[0] if first_user else "session").strip()
    if len(title) > 30:
        title = title[:30]
    safe_title = "".join(ch for ch in title if ch not in '\\/:*?"<>|' and ord(ch) >= 32) or "session"

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}_{safe_title}.jsonl"
    file_path = export_dir / filename

    items: List[ChatExportItem] = []
    with file_path.open("w", encoding="utf-8") as f:
        for t in turns:
            item = ChatExportItem(
                user=t.get("user", ""),
                assistant=t.get("assistant", ""),
                ts=t.get("ts", ""),
            )
            items.append(item)
            f.write(item.model_dump_json(ensure_ascii=False) + "\n")

    rel_path = str(file_path.relative_to(project_root))
    return ChatExportResponse(session_id=x_session_id, turns=items, file_path=rel_path)


@app.get("/api/v1/chat/history", response_model=ChatHistoryResponse)
async def chat_history_api(x_session_id: str | None = Header(default=None), limit: int = 50):
    """
    获取当前 session 的最近对话轮次（用于前端展示聊天记录）。
    """
    if not x_session_id:
        raise HTTPException(status_code=400, detail="missing x-session-id header")

    turns_raw = _load_history_turns(x_session_id, limit=limit)
    if not turns_raw:
        return ChatHistoryResponse(session_id=x_session_id, turns=[])

    items: List[ChatExportItem] = []
    for t in turns_raw:
        items.append(
            ChatExportItem(
                user=t.get("user", ""),
                assistant=t.get("assistant", ""),
                ts=t.get("ts", ""),
            )
        )

    return ChatHistoryResponse(session_id=x_session_id, turns=items)


# ==========================================================
# Phase 3: OpenAI 兼容适配层（供 SillyTavern Group Chat 接入）
# ==========================================================
# 详见 docs/SillyTavern_Integration.md。

AXIODRASIL_MODEL_ID = "axiodrasil-cabinet"
CABINET_PERSONA_IDS = list(PERSONA_META.keys())


class OpenAIChatMessage(BaseModel):
    role: str
    content: str = ""


class OpenAIChatCompletionRequest(BaseModel):
    model: str = AXIODRASIL_MODEL_ID
    messages: List[OpenAIChatMessage]
    stream: bool = False
    user: Optional[str] = None


def _resolve_session_id(x_session_id: Optional[str], authorization: Optional[str], user_field: Optional[str]) -> str:
    """把酒馆的会话身份映射到内阁的 thread_id/x-session-id。

    优先级：
    1. `x-session-id` 自定义请求头（Group Chat 强烈建议固定同一值）
    2. `Authorization` 头里的 API Key
    3. OpenAI 请求体里的 `user` 字段
    4. 兜底 `sillytavern-default`
    """
    if x_session_id and x_session_id.strip():
        return x_session_id.strip()
    if authorization and authorization.strip():
        digest = hashlib.sha256(authorization.strip().encode("utf-8")).hexdigest()[:16]
        return f"st-authkey-{digest}"
    if user_field and user_field.strip():
        return f"st-user-{user_field.strip()}"
    return "sillytavern-default"


@app.get("/v1/models")
async def openai_compat_models():
    """SillyTavern：返回内阁总模型 + 12 个人设模型（便于 Group 成员各自绑定）。"""
    data = [
        {
            "id": AXIODRASIL_MODEL_ID,
            "object": "model",
            "created": 0,
            "owned_by": "axiodrasil",
        }
    ]
    for pid in CABINET_PERSONA_IDS:
        data.append(
            {
                "id": f"axiodrasil-{pid}",
                "object": "model",
                "created": 0,
                "owned_by": "axiodrasil",
            }
        )
    return {"object": "list", "data": data}


@app.post("/api/v1/cabinet/consensus")
async def cabinet_consensus_api(x_session_id: str | None = Header(default=None)):
    """显式散会：压缩 M1 吵架层 → M3 共识层。"""
    if not x_session_id or not x_session_id.strip():
        raise HTTPException(status_code=400, detail="missing x-session-id header")
    session_id = x_session_id.strip()
    try:
        summary = close_and_compress(session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"consensus failed: {exc}") from exc
    return {
        "session_id": session_id,
        "ok": True,
        "summary": summary or "",
        "message": "已散会并写入共识" if summary else "无进行中的吵架缓冲，已关闭吵架状态",
    }


@app.post("/v1/chat/completions")
async def openai_compat_chat_completions(
    payload: OpenAIChatCompletionRequest,
    x_session_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    x_persona: str | None = Header(default=None),
):
    session_id = _resolve_session_id(x_session_id, authorization, payload.user)

    user_text = ""
    for msg in reversed(payload.messages):
        if msg.role == "user" and msg.content.strip():
            user_text = msg.content
            break
    if not user_text:
        raise HTTPException(status_code=400, detail="no user message found in messages[]")

    forced = _resolve_forced_persona(
        x_persona=x_persona,
        model=payload.model,
        messages=payload.messages,
    )
    # Group Chat：有强制人设时去前缀；无强制时保持旧单卡前缀行为
    group_mode = forced is not None
    chat_payload = ChatRequest(
        text=user_text,
        forced_persona=forced,
        strip_persona_prefix=group_mode,
    )
    try:
        reply, _intent, _trace_raw, _active, active_persona = _execute_turn(
            chat_payload, session_id
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"turn failed: {exc}") from exc

    _after_turn_memory(
        session_id,
        user_text,
        reply,
        active_persona,
        group_mode=group_mode,
    )

    created_ts = int(datetime.now(timezone.utc).timestamp())
    completion_id = f"chatcmpl-{uuid4().hex[:24]}"

    est_prompt_tokens = max(1, len(user_text) // 4)
    est_completion_tokens = max(1, len(reply) // 4)

    if payload.stream:
        async def event_gen():
            first_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": payload.model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"

            chunk_size = 20
            for i in range(0, len(reply), chunk_size):
                piece = reply[i : i + chunk_size]
                chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": payload.model,
                    "choices": [{"index": 0, "delta": {"content": piece}, "finish_reason": None}],
                }
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)

            final_chunk = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": payload.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {json.dumps(final_chunk, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_gen(), media_type="text/event-stream")

    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_ts,
        "model": payload.model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": est_prompt_tokens,
            "completion_tokens": est_completion_tokens,
            "total_tokens": est_prompt_tokens + est_completion_tokens,
        },
    }