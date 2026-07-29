/**
 * 浏览器侧矩阵客户端：经 Next BFF 调用 Host Ports。
 */

import type {
  ChatStreamMeta,
  ChatTurn,
  ConsensusResult,
  HealthStatus,
  PersonaCard,
  StreamChatInput,
} from "./types";

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
  const res = await fetch(`/api/personas/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`persona ${id} failed: ${res.status}`);
  return (await res.json()) as PersonaCard;
}

export async function fetchHistory(sessionId: string, limit = 50): Promise<ChatTurn[]> {
  const res = await fetch(`/api/chat/history?limit=${limit}`, {
    headers: { "x-session-id": sessionId },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`history failed: ${res.status}`);
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

export async function streamChat(input: StreamChatInput): Promise<{
  reply: string;
  meta: ChatStreamMeta | null;
}> {
  const body: Record<string, unknown> = {
    text: input.text,
    strip_persona_prefix: Boolean(input.stripPersonaPrefix),
  };
  if (input.forcedPersona) body.forced_persona = input.forcedPersona;
  if (input.workflowMode && input.workflowMode !== "default") {
    body.workflow_mode = input.workflowMode;
  }

  const res = await fetch("/api/chat/stream", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-session-id": input.sessionId,
    },
    body: JSON.stringify(body),
    signal: input.signal,
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
      if (rec.type === "delta" && typeof rec.content === "string") {
        reply += rec.content;
        input.onDelta?.(rec.content);
      } else if (rec.type === "done") {
        // noop
      } else if ("session_id" in rec) {
        meta = rec as unknown as ChatStreamMeta;
        input.onMeta?.(meta);
      }
    }
  }

  return { reply, meta };
}

export function stripPersonaPrefix(text: string): string {
  return (text || "").replace(/^\s*\[[^\]]+]\s*[:：]\s*/, "");
}

export function parsePersonaFromReply(text: string): string {
  const m = /^\s*\[([^\]]+)]\s*[:：]/.exec(text || "");
  return m ? m[1].trim().toLowerCase() : "";
}
