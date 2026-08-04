from uuid import uuid4
import hashlib
import re
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from agents.persona_meta import PERSONA_META, PERSONA_TO_ROUTE, SUMMON_ALIASES
from agents.proactive import (
    drain_pending,
    get_presence,
    set_persist_turn,
    set_presence,
    start_proactive_loop,
    stop_proactive_loop,
)
from infrastructure.container import get_chat_model, get_llm_provider
from memory.cabinet_layers import close_and_compress
from modules.chat_api.service import (
    TurnRequest,
    get_shared_session_cache,
    get_turn_service,
    resolve_group_mode,
)
from schemas.protocols import TaskIntent
from schemas.trace import TraceStep


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    set_persist_turn(_persist_turn)
    await start_proactive_loop()
    try:
        yield
    finally:
        await stop_proactive_loop()


app = FastAPI(title="Axiodrasil Core API", version="1.0.0", lifespan=_lifespan)

session_cache = get_shared_session_cache()
turn_service = get_turn_service()

# Host 接口矩阵：personas 与 bootstrap 解耦，避免矩阵失败导致角色卡 404 / 前端永久接通中
try:
    from modules.personas.routes import router as personas_router

    app.include_router(personas_router)
except Exception as _personas_exc:  # pragma: no cover
    print(f"[host] personas router mount failed: {_personas_exc}")

try:
    from app.registry import bootstrap_registry, get_registry

    bootstrap_registry()
    app.state.matrix = get_registry()  # type: ignore[attr-defined]
except Exception as _matrix_exc:  # pragma: no cover
    print(f"[host] matrix bootstrap failed: {_matrix_exc}")

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


def _persist_turn(session_id: str, user_text: str, assistant_text: str) -> None:
    """供 proactive 注册；委托 SessionHistory 双写。"""
    from memory.session_history import append_turn

    append_turn(
        session_id,
        user_text,
        assistant_text,
        session_cache=session_cache,
    )


def _load_history_turns(session_id: str, limit: int = 50) -> list[dict]:
    return turn_service.load_history_ui(session_id, limit=limit)


def _to_turn_request(
    payload: "ChatRequest",
    *,
    memory_thread_id: str | None = None,
) -> TurnRequest:
    return TurnRequest(
        text=payload.text,
        workflow_mode=payload.workflow_mode,
        forced_persona=payload.forced_persona,
        strip_persona_prefix=payload.strip_persona_prefix,
        group_mode=payload.group_mode,
        memory_thread_id=memory_thread_id,
    )


def _execute_turn(
    payload: "ChatRequest",
    session_id: str,
    *,
    memory_thread_id: str | None = None,
):
    """兼容壳：委托 TurnService.run。"""
    result = turn_service.run(
        _to_turn_request(payload, memory_thread_id=memory_thread_id),
        session_id,
    )
    return (
        result.reply,
        result.intent,
        result.trace_raw,
        result.active_task_type,
        result.active_persona,
    )


def _resolve_group_mode(payload: "ChatRequest") -> bool:
    return resolve_group_mode(_to_turn_request(payload))


def _after_turn_memory(
    session_id: str,
    user_text: str,
    reply_for_client: str,
    active_persona: str,
    *,
    group_mode: bool,
    memory_thread_id: str | None = None,
) -> str:
    return turn_service.after_turn(
        session_id,
        user_text,
        reply_for_client,
        active_persona,
        group_mode=group_mode,
        memory_thread_id=memory_thread_id,
    )


@app.get("/api/v1/health")
def api_health():
    """轻量探活：供 Next 开发代理与运维脚本探测；不调用大模型。"""
    # SessionCache.ping 内含熔断，Redis 宕机时不会每请求拖满 socket_timeout
    redis_ok = session_cache.ping()
    return {
        "ok": True,
        "redis": redis_ok,
        "llm_provider": get_llm_provider(),
        "chat_model": get_chat_model(),
    }


class PresenceRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)
    memory_thread_id: Optional[str] = Field(
        default=None,
        description="共享记忆池 ID；缺省等同 session_id",
    )


class PresenceResponse(BaseModel):
    ok: bool = True
    session_id: str
    memory_thread_id: str


@app.post("/api/v1/presence", response_model=PresenceResponse)
def presence_api(payload: PresenceRequest):
    """Solo 前端上报当前活跃对话，供主动开口落点。"""
    try:
        target = set_presence(payload.session_id, payload.memory_thread_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return PresenceResponse(
        session_id=target.session_id,
        memory_thread_id=target.memory_thread_id,
    )


@app.get("/api/v1/presence")
def presence_get_api():
    target = get_presence()
    if target is None:
        return {"ok": True, "session_id": None, "memory_thread_id": None}
    return {
        "ok": True,
        "session_id": target.session_id,
        "memory_thread_id": target.memory_thread_id,
        "updated_at": target.updated_at,
    }


@app.get("/api/v1/proactive/pending")
def proactive_pending_api():
    """托盘拉取未读主动消息；拉取后标记已读。"""
    items = drain_pending(mark_consumed=True)
    return {"ok": True, "items": items}


class AttachmentIngestResponse(BaseModel):
    name: str
    kind: Literal["text", "image"]
    text: str
    truncated: bool = False


class SttResponse(BaseModel):
    text: str


@app.post("/api/v1/attachments/ingest", response_model=AttachmentIngestResponse)
async def attachments_ingest_api(file: UploadFile = File(...)):
    """Solo 附件消化：文本抽取或图片 VL 描述 → 纯文本，供拼进 chat。"""
    from modules.attachments.service import AttachmentError, ingest_bytes

    data = await file.read()
    try:
        result = ingest_bytes(
            data,
            filename=file.filename or "upload",
            content_type=file.content_type or "",
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return AttachmentIngestResponse(
        name=result.name,
        kind=result.kind,
        text=result.text,
        truncated=result.truncated,
    )


@app.post("/api/v1/stt", response_model=SttResponse)
async def stt_api(audio: UploadFile = File(...)):
    """服务端语音转写（浏览器 Web Speech 不可用时的回退）。"""
    from modules.stt.service import SttError, transcribe_audio

    data = await audio.read()
    try:
        text = transcribe_audio(
            data,
            filename=audio.filename or "audio.webm",
            content_type=audio.content_type or "",
        )
    except SttError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return SttResponse(text=text)


class ImageGenerateRequest(BaseModel):
    persona_id: str = Field(default="bina", min_length=1, max_length=64)
    scene: str = Field(default="", max_length=2000)
    mode: Literal["selfie", "scene"] = "selfie"


class ImageGenerateResponse(BaseModel):
    persona_id: str
    url: str
    prompt: str


@app.get("/api/v1/images/persona/{persona_id}")
def image_persona_profile_api(persona_id: str):
    """查看人格定妆配置（不含密钥；用于确认 LoRA 是否挂上）。"""
    from modules.image_gen.profiles import load_visual_profile, profile_to_public

    profile = load_visual_profile(persona_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="未找到视觉定妆配置")
    return profile_to_public(profile)


@app.post("/api/v1/images/generate", response_model=ImageGenerateResponse)
def image_generate_api(payload: ImageGenerateRequest):
    """ComfyUI + 定妆 LoRA 出图（需本机 ComfyUI :8188）。"""
    from modules.image_gen.service import ImageGenError, generate_persona_image

    try:
        img = generate_persona_image(
            payload.persona_id,
            scene=payload.scene,
            mode=payload.mode,
        )
    except ImageGenError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    return ImageGenerateResponse(
        persona_id=img.persona_id,
        url=img.relative_url,
        prompt=img.prompt,
    )


@app.get("/api/v1/images/file/{file_name}")
def image_file_api(file_name: str):
    """读取已生成图片。"""
    import os
    from pathlib import Path

    from fastapi.responses import FileResponse

    safe = Path(file_name).name
    if safe != file_name or ".." in file_name:
        raise HTTPException(status_code=400, detail="非法文件名")
    root = Path(os.getenv("AX_IMAGE_OUT_DIR") or (Path(__file__).resolve().parent / "data" / "generated"))
    path = root / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    media = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return FileResponse(path, media_type=media)


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
    group_mode: Optional[bool] = Field(
        default=None,
        description="True=群聊写 M1；False=单聊不写 M1（仍可写 M2 私忆）。缺省时回退为 bool(forced_persona)",
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


@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat_api(
    payload: ChatRequest,
    response: Response,
    background_tasks: BackgroundTasks,
    x_session_id: str | None = Header(default=None),
    x_trace_id: str | None = Header(default=None, alias="x-trace-id"),
    x_memory_thread: str | None = Header(default=None, alias="x-memory-thread"),
):
    session_id = x_session_id or str(uuid4())
    memory_thread_id = (x_memory_thread or "").strip() or session_id
    trace_id = (x_trace_id or "").strip() or str(uuid4())
    response.headers["X-Trace-Id"] = trace_id

    try:
        reply, intent, trace_raw, _active, active_persona = _execute_turn(
            payload, session_id, memory_thread_id=memory_thread_id
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"turn failed: {exc}") from exc

    group_mode = _resolve_group_mode(payload)
    # 先回客户端，再后台写 L1/M2，降低可感知等待
    def _persist_bg() -> None:
        _after_turn_memory(
            session_id,
            payload.text,
            reply,
            active_persona,
            group_mode=group_mode,
            memory_thread_id=memory_thread_id,
        )

    background_tasks.add_task(_persist_bg)

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
    x_memory_thread: str | None = Header(default=None, alias="x-memory-thread"),
):
    """
    SSE 流式输出接口：返回 text/event-stream。

    仍为伪流式（整轮完成后再切块），但在 `_execute_turn` 期间定期发 heartbeat，
    避免前端/代理以为连接挂死。
    """
    session_id = x_session_id or str(uuid4())
    memory_thread_id = (x_memory_thread or "").strip() or session_id
    trace_id = (x_trace_id or "").strip() or str(uuid4())
    group_mode = _resolve_group_mode(payload)

    def _run_turn_only():
        return _execute_turn(payload, session_id, memory_thread_id=memory_thread_id)

    async def event_gen():
        yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"

        turn_task = asyncio.create_task(asyncio.to_thread(_run_turn_only))
        while not turn_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(turn_task), timeout=2.0)
            except asyncio.TimeoutError:
                yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"

        try:
            reply, intent, trace_raw, _active, active_persona = turn_task.result()
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            yield f"data: {json.dumps({'type': 'error', 'detail': detail}, ensure_ascii=False)}\n\n"
            return
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'detail': f'turn failed: {exc}'}, ensure_ascii=False)}\n\n"
            return

        # 先吐字，再后台持久化
        def _persist_bg() -> None:
            _after_turn_memory(
                session_id,
                payload.text,
                reply,
                active_persona,
                group_mode=group_mode,
                memory_thread_id=memory_thread_id,
            )

        asyncio.create_task(asyncio.to_thread(_persist_bg))

        trace_payload = [TraceStep.model_validate(s).model_dump() for s in trace_raw]
        meta = {
            "session_id": session_id,
            "intent": intent.model_dump(),
            "trace_id": trace_id,
            "trace": trace_payload,
            "workflow_mode": payload.workflow_mode,
            "active_persona": active_persona,
        }
        yield f"data: {json.dumps(meta, ensure_ascii=False)}\n\n"

        chunk_size = 12
        for i in range(0, len(reply), chunk_size):
            piece = reply[i : i + chunk_size]
            data = {"type": "delta", "content": piece}
            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"X-Trace-Id": trace_id, "Cache-Control": "no-cache"},
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
    # Group Chat：有强制人设时去前缀并写 M1；无强制时保持旧单卡前缀行为
    group_mode = forced is not None
    chat_payload = ChatRequest(
        text=user_text,
        forced_persona=forced,
        strip_persona_prefix=group_mode,
        group_mode=group_mode,
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