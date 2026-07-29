"use client";

import type { PersonaCard } from "@/matrix/types";
import { stripPersonaPrefix } from "@/matrix/client";
import { PersonaAvatar } from "@/modules/persona-cards/PersonaAvatar";

export type BubbleMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  personaId?: string;
  pending?: boolean;
};

export function MessageList({
  messages,
  personaMap,
  emptyTitle = "内阁议事厅",
  emptyHint = "点名成员发言，或直接提问由路由决定执勤人设。",
}: {
  messages: BubbleMessage[];
  personaMap: Record<string, PersonaCard>;
  emptyTitle?: string;
  emptyHint?: string;
}) {
  return (
    <div className="flex flex-1 flex-col gap-3 overflow-y-auto px-1 py-2">
      {messages.length === 0 ? (
        <div className="ax-empty flex flex-1 flex-col items-center justify-center gap-2 text-center">
          <p className="font-[family-name:var(--font-display)] text-2xl tracking-wide text-[var(--ax-fg)]">
            {emptyTitle}
          </p>
          <p className="max-w-sm text-sm text-[var(--ax-muted)]">{emptyHint}</p>
        </div>
      ) : null}
      {messages.map((m) => {
        if (m.role === "user") {
          return (
            <div key={m.id} className="flex justify-end">
              <div className="ax-bubble-user max-w-[85%] whitespace-pre-wrap px-4 py-2.5 text-sm leading-relaxed">
                {m.content}
              </div>
            </div>
          );
        }
        const persona = m.personaId ? personaMap[m.personaId] : undefined;
        return (
          <div key={m.id} className="flex items-start gap-2">
            <PersonaAvatar persona={persona || { id: m.personaId || "?", name: "?", color: "#8b7355" }} />
            <div className="min-w-0 max-w-[85%]">
              <div className="mb-1 flex items-center gap-2 text-xs text-[var(--ax-muted)]">
                <span style={{ color: persona?.color }}>{persona?.name || m.personaId || "内阁"}</span>
                {persona?.title ? <span>· {persona.title}</span> : null}
              </div>
              <div
                className="ax-bubble-assistant whitespace-pre-wrap px-4 py-2.5 text-sm leading-relaxed"
                style={{ borderLeftColor: persona?.color || "var(--ax-line)" }}
              >
                {m.pending && !m.content ? (
                  <span className="ax-typing text-[var(--ax-muted)]">正在议事…</span>
                ) : (
                  stripPersonaPrefix(m.content)
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
