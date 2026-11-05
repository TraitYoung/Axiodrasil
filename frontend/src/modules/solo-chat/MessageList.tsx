"use client";

import type { ReactNode } from "react";
import type { PersonaCard } from "@/matrix/types";
import { stripPersonaPrefix } from "@/matrix/client";
import { PersonaAvatar } from "@/modules/persona-cards/PersonaAvatar";

const MD_IMAGE_RE = /!\[([^\]]*)]\(([^)\s]+)\)/g;

/** 把 markdown 图片拆成文本 + <img>（用于 Bina 自拍等） */
function renderContentWithImages(raw: string): ReactNode {
  const text = stripPersonaPrefix(raw || "");
  const nodes: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  const re = new RegExp(MD_IMAGE_RE.source, "g");
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) {
      nodes.push(
        <span key={`t-${last}`} className="whitespace-pre-wrap">
          {text.slice(last, m.index)}
        </span>,
      );
    }
    const alt = m[1] || "image";
    const src = m[2];
    nodes.push(
      // eslint-disable-next-line @next/next/no-img-element
      <img
        key={`i-${m.index}`}
        src={src}
        alt={alt}
        className="my-2 max-h-80 max-w-full rounded-lg border border-[var(--ax-line)] object-contain"
      />,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) {
    nodes.push(
      <span key={`t-${last}`} className="whitespace-pre-wrap">
        {text.slice(last)}
      </span>,
    );
  }
  return nodes.length ? nodes : text;
}

export type BubbleAttachment = {
  name: string;
  kind: "text" | "image";
  previewUrl?: string;
};

export type BubbleMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  personaId?: string;
  pending?: boolean;
  hint?: string;
  /** 当前会话本地附件预览（历史回合通常无） */
  attachments?: BubbleAttachment[];
};

export function MessageList({
  messages,
  personaMap,
  emptyTitle = "内阁议事厅",
  emptyHint = "点名成员发言，或直接提问由路由决定执勤人设。",
  statusHint,
  pendingLabel = "正在议事…",
}: {
  messages: BubbleMessage[];
  personaMap: Record<string, PersonaCard>;
  emptyTitle?: string;
  emptyHint?: string;
  statusHint?: string | null;
  /** 流式等待时的占位文案；单聊可换成更亲昵的说法 */
  pendingLabel?: string;
}) {
  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-1 py-2">
      {statusHint ? (
        <p className="px-1 text-center text-xs tracking-wide text-[var(--ax-muted)]">{statusHint}</p>
      ) : null}
      {messages.length === 0 ? (
        <div className="ax-empty flex flex-1 flex-col items-center justify-center gap-2 text-center">
          <p className="font-[family-name:var(--font-display)] text-2xl tracking-wide text-[var(--ax-fg)]">
            {emptyTitle}
          </p>
          <p className="max-w-sm text-sm text-[var(--ax-muted)]">{emptyHint}</p>
        </div>
      ) : null}
      {messages.map((m) => {
        if (m.role === "system") {
          return (
            <div key={m.id} className="flex justify-center">
              <p className="max-w-[90%] text-center text-xs text-[var(--ax-muted)]">{m.content}</p>
            </div>
          );
        }
        if (m.role === "user") {
          return (
            <div key={m.id} className="ax-msg flex justify-end">
              <div className="ax-bubble-user max-w-[85%] space-y-2 px-4 py-2.5 text-sm leading-relaxed">
                {m.attachments?.length ? (
                  <div className="flex flex-wrap gap-2">
                    {m.attachments.map((a) =>
                      a.kind === "image" && a.previewUrl ? (
                        // eslint-disable-next-line @next/next/no-img-element
                        <img
                          key={a.name + (a.previewUrl || "")}
                          src={a.previewUrl}
                          alt={a.name}
                          className="max-h-40 max-w-full rounded-lg object-contain"
                        />
                      ) : (
                        <span
                          key={a.name}
                          className="rounded-md bg-black/10 px-2 py-0.5 text-xs"
                        >
                          {a.kind === "image" ? "图片" : "附件"} · {a.name}
                        </span>
                      ),
                    )}
                  </div>
                ) : null}
                {m.content ? (
                  <div className="whitespace-pre-wrap">{m.content}</div>
                ) : null}
              </div>
            </div>
          );
        }
        const persona = m.personaId ? personaMap[m.personaId] : undefined;
        return (
          <div key={m.id} className="ax-msg flex items-start gap-2">
            <PersonaAvatar persona={persona || { id: m.personaId || "?", name: "?", color: "#8b7355" }} />
            <div className="min-w-0 max-w-[85%]">
              <div className="mb-1 flex items-center gap-2 text-xs text-[var(--ax-muted)]">
                <span style={{ color: persona?.color }}>{persona?.name || m.personaId || "内阁"}</span>
                {persona?.title ? <span>· {persona.title}</span> : null}
                {m.hint ? <span className="opacity-80">· {m.hint}</span> : null}
              </div>
              <div
                className="ax-bubble-assistant whitespace-pre-wrap px-4 py-2.5 text-sm leading-relaxed"
                style={{ borderLeftColor: persona?.color || "var(--ax-line)" }}
              >
                {m.pending && !m.content ? (
                  <span className="text-[var(--ax-muted)]">
                    <span key={pendingLabel} className="ax-cute-line inline-block">
                      {pendingLabel}
                    </span>
                    <span className="ax-typing-dots" aria-hidden="true">
                      <span />
                      <span />
                      <span />
                    </span>
                  </span>
                ) : (
                  renderContentWithImages(m.content)
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
