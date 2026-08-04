/**
 * 前端接口矩阵类型（与后端 app/matrix/ports 语义对齐）。
 */

export type HealthStatus = {
  ok: boolean;
  redis?: boolean;
  llm_provider?: string;
  chat_model?: string;
};

export type ChatTurn = {
  user: string;
  assistant: string;
  ts: string;
  persona?: string;
};

export type PersonaCard = {
  id: string;
  name: string;
  title: string;
  description: string;
  personality: string;
  greeting: string;
  model_id: string;
  color: string;
  avatar: string;
};

export type ChatStreamMeta = {
  session_id: string;
  intent?: Record<string, unknown>;
  trace_id?: string;
  trace?: unknown[];
  workflow_mode?: string;
  active_persona?: string;
};

export type StreamChatInput = {
  text: string;
  sessionId: string;
  /** 共享记忆池；Solo 多谈话时固定，与 sessionId（气泡）分离 */
  memoryThreadId?: string;
  forcedPersona?: string | null;
  stripPersonaPrefix?: boolean;
  /** true=群聊写 M1；false=单聊不写 M1。缺省由后端按 forced_persona 回退。 */
  groupMode?: boolean;
  workflowMode?: string;
  signal?: AbortSignal;
  onMeta?: (meta: ChatStreamMeta) => void;
  onDelta?: (chunk: string) => void;
};

export type ConsensusResult = {
  session_id: string;
  ok: boolean;
  summary: string;
  message: string;
};

export type AttachmentIngestResult = {
  name: string;
  kind: "text" | "image";
  text: string;
  truncated: boolean;
};

export type SttResult = {
  text: string;
};

export const GROUP_SESSION_ID = "ax-cabinet-main";

export function soloSessionId(personaId: string, userLocalId: string): string {
  const pid = (personaId || "unknown").trim().toLowerCase();
  const uid = (userLocalId || "local").replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 32) || "local";
  return `ax-solo-${pid}-${uid}`;
}
