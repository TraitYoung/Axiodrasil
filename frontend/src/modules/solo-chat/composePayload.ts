/** 把手打文字与附件块拼成 chat text（上限 12000）。 */

export const CHAT_TEXT_MAX = 12000;

export type PendingAttachment = {
  id: string;
  name: string;
  kind: "text" | "image";
  /** 服务端抽出的正文或图片描述 */
  text: string;
  truncated?: boolean;
  /** 当前会话本地预览（图片） */
  previewUrl?: string;
};

export function formatAttachmentBlock(att: PendingAttachment): string {
  if (att.kind === "image") {
    return `【图片: ${att.name}】\n（视觉描述：${att.text}）`;
  }
  const note = att.truncated ? "\n…(已截断)" : "";
  return `【附件: ${att.name}】\n${att.text}${note}`;
}

export function composeChatPayload(
  typed: string,
  attachments: PendingAttachment[],
  maxLen = CHAT_TEXT_MAX,
): string {
  const body = typed.trim();
  const blocks = attachments.map(formatAttachmentBlock);
  let out = [body, ...blocks].filter(Boolean).join("\n\n").trim();
  if (out.length <= maxLen) return out;
  out = out.slice(0, maxLen - 12).trimEnd() + "\n…(已截断)";
  return out;
}

export function canSendChat(typed: string, attachments: PendingAttachment[]): boolean {
  return Boolean(typed.trim() || attachments.length > 0);
}
