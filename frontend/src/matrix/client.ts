/**
 * 浏览器侧矩阵客户端：经 Next BFF 调用 Host Ports。
 */

import type {
  AttachmentIngestResult,
  ChatStreamMeta,
  ChatTurn,
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
