/**
 * 浏览器侧矩阵客户端：经 Next BFF 调用 Host Ports。
 */

import type {
  AttachmentIngestResult,
  ChatStreamMeta,
  ChatTurn,
  ConsensusResult,
  HealthStatus,
  PersonaCard,
  SttResult,
  StreamChatInput,
} from "./types";

async function readApiError(res: Response, fallback: string): Promise<string> {
  const text = await res.text().catch(() => "");
  if (!text) return fallback;
  try {
    const data = JSON.parse(text) as { detail?: unknown };
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((x) => (typeof x === "object" && x && "msg" in x ? String((x as { msg: unknown }).msg) : String(x)))
        .join("; ");
    }
  } catch {
    // plain text
  }
  return text;
}

function safeParseJson(line: string): unknown | null {
  try {
    return JSON.parse(line);
  } catch {
    return null;
  }
}

export async function healthCheck(): Promise<HealthStatus> {
  const res = await fetch("/api/health", { cache: "no-store" });
  if (!res.ok) return { ok: false };
  return (await res.json()) as HealthStatus;
}

export async function listPersonas(): Promise<PersonaCard[]> {
  const res = await fetch("/api/personas", { cache: "no-store" });
  if (!res.ok) throw new Error(`personas failed: ${res.status}`);
  const data = (await res.json()) as { personas: PersonaCard[] };
  return data.personas || [];
}

export async function getPersona(id: string): Promise<PersonaCard> {
  const res = await fetch(`/api/personas/${encodeURIComponent(id)}`, {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `persona ${id} failed: ${res.status}`);
  }
  return (await res.json()) as PersonaCard;
}

export async function reportPresence(
  sessionId: string,
  memoryThreadId?: string,
): Promise<void> {
  const res = await fetch("/api/presence", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      session_id: sessionId,
      memory_thread_id: memoryThreadId || sessionId,
    }),
    signal: AbortSignal.timeout(5_000),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `presence failed: ${res.status}`);
  }
}

export async function fetchHistory(sessionId: string, limit = 50): Promise<ChatTurn[]> {
  const res = await fetch(`/api/chat/history?limit=${limit}`, {
    headers: { "x-session-id": sessionId },
    cache: "no-store",
    signal: AbortSignal.timeout(12_000),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `history failed: ${res.status}`);
  }
  const data = (await res.json()) as { turns: ChatTurn[] };
  return (data.turns || []).map((t) => {
    const m = /^\s*\[([^\]]+)]\s*[:：]/.exec(t.assistant || "");
    return { ...t, persona: t.persona || (m ? m[1].trim().toLowerCase() : "") };
  });
}

export async function cabinetConsensus(sessionId: string): Promise<ConsensusResult> {
  const res = await fetch("/api/cabinet/consensus", {
    method: "POST",
    headers: { "x-session-id": sessionId },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `consensus failed: ${res.status}`);
  }
  return (await res.json()) as ConsensusResult;
}

/** Solo 主路径：同步 JSON（经 Next rewrite → FastAPI），无伪 SSE 切块开销 */
export async function sendChat(input: StreamChatInput): Promise<{
  reply: string;
  meta: ChatStreamMeta | null;
}> {
  const body: Record<string, unknown> = {
    text: input.text,
    strip_persona_prefix: Boolean(input.stripPersonaPrefix),
  };
  if (input.forcedPersona) body.forced_persona = input.forcedPersona;
  if (typeof input.groupMode === "boolean") body.group_mode = input.groupMode;
  if (input.workflowMode && input.workflowMode !== "default") {
    body.workflow_mode = input.workflowMode;
  }

  const signal =
    input.signal ??
    (typeof AbortSignal !== "undefined" && "timeout" in AbortSignal
      ? AbortSignal.timeout(120_000)
      : undefined);

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "x-session-id": input.sessionId,
  };
  if (input.memoryThreadId) {
    headers["x-memory-thread"] = input.memoryThreadId;
  }

  const res = await fetch("/api/v1/chat", {
    method: "POST",
    headers,
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `chat failed: ${res.status}`);
  }

  const data = (await res.json()) as {
    reply?: string;
    session_id?: string;
    active_persona?: string;
    intent?: Record<string, unknown>;
    trace_id?: string;
    trace?: unknown[];
  };
  const reply = typeof data.reply === "string" ? data.reply : "";
  if (!reply) {
    throw new Error("回复中断了，内线没有传回内容。可点「重新接通」或再发一次。");
  }
  const meta: ChatStreamMeta = {
    session_id: data.session_id || input.sessionId,
    active_persona: data.active_persona,
    intent: data.intent,
    trace_id: data.trace_id,
    trace: data.trace,
  };
  input.onMeta?.(meta);
  input.onDelta?.(reply);
  return { reply, meta };
}

export async function streamChat(input: StreamChatInput): Promise<{
  reply: string;
  meta: ChatStreamMeta | null;
}> {
  const body: Record<string, unknown> = {
    text: input.text,
    strip_persona_prefix: Boolean(input.stripPersonaPrefix),
  };
  if (input.forcedPersona) body.forced_persona = input.forcedPersona;
  if (typeof input.groupMode === "boolean") body.group_mode = input.groupMode;
  if (input.workflowMode && input.workflowMode !== "default") {
    body.workflow_mode = input.workflowMode;
  }

  // 默认 120s：伪流式整轮 LLM 可能较慢，但不能无限挂起
  const signal =
    input.signal ??
    (typeof AbortSignal !== "undefined" && "timeout" in AbortSignal
      ? AbortSignal.timeout(120_000)
      : undefined);

  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-session-id": input.sessionId,
    },
    body: JSON.stringify(body),
    signal,
  });

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `stream failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let reply = "";
  let meta: ChatStreamMeta | null = null;
  let sawDone = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() || "";
    for (const part of parts) {
      const line = part
        .split("\n")
        .map((l) => l.trim())
        .find((l) => l.startsWith("data:"));
      if (!line) continue;
      const payload = line.replace(/^data:\s*/, "");
      const obj = safeParseJson(payload);
      if (!obj || typeof obj !== "object") continue;
      const rec = obj as Record<string, unknown>;
      if (rec.type === "heartbeat") {
        continue;
      }
      if (rec.type === "error") {
        const detail = typeof rec.detail === "string" ? rec.detail : "stream error";
        throw new Error(detail);
      }
      if (rec.type === "delta" && typeof rec.content === "string") {
        reply += rec.content;
        input.onDelta?.(rec.content);
      } else if (rec.type === "done") {
        sawDone = true;
      } else if ("session_id" in rec) {
        meta = rec as unknown as ChatStreamMeta;
        input.onMeta?.(meta);
      }
    }
  }

  if (!reply && !sawDone) {
    throw new Error("回复中断了，内线没有传回内容。可点「重新接通」或再发一次。");
  }

  return { reply, meta };
}

/** 文本/图片附件 → 服务端抽出或 VL 描述 */
export async function ingestAttachment(
  file: File,
  sessionId?: string,
): Promise<AttachmentIngestResult> {
  const body = new FormData();
  body.append("file", file, file.name);
  const headers: Record<string, string> = {};
  if (sessionId) headers["x-session-id"] = sessionId;
  const res = await fetch("/api/v1/attachments/ingest", {
    method: "POST",
    headers,
    body,
    signal: AbortSignal.timeout(120_000),
  });
  if (!res.ok) {
    throw new Error(await readApiError(res, `附件处理失败: ${res.status}`));
  }
  return (await res.json()) as AttachmentIngestResult;
}

/** 服务端 STT（Web Speech 回退） */
export async function transcribeAudio(
  blob: Blob,
  sessionId?: string,
  filename = "audio.webm",
): Promise<SttResult> {
  const body = new FormData();
  body.append("audio", blob, filename);
  const headers: Record<string, string> = {};
  if (sessionId) headers["x-session-id"] = sessionId;
  const res = await fetch("/api/v1/stt", {
    method: "POST",
    headers,
    body,
    signal: AbortSignal.timeout(120_000),
  });
  if (!res.ok) {
    throw new Error(await readApiError(res, `语音识别失败: ${res.status}`));
  }
  return (await res.json()) as SttResult;
}

export function stripPersonaPrefix(text: string): string {
  return (text || "").replace(/^\s*\[[^\]]+]\s*[:：]\s*/, "");
}

export function parsePersonaFromReply(text: string): string {
  const m = /^\s*\[([^\]]+)]\s*[:：]/.exec(text || "");
  return m ? m[1].trim().toLowerCase() : "";
}
