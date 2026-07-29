"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/host/AppShell";
import { useUserLocalId } from "@/infra/session";
import {
  fetchHistory,
  listPersonas,
  parsePersonaFromReply,
  streamChat,
} from "@/matrix/client";
import { soloSessionId, type PersonaCard } from "@/matrix/types";
import { PersonaCardTile } from "@/modules/persona-cards/PersonaCardTile";
import { MessageList, type BubbleMessage } from "@/modules/group-chat/MessageList";

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

const SELECTED_KEY = "ax-solo-persona";

export function SoloChatView() {
  const userLocalId = useUserLocalId();
  const [cards, setCards] = useState<PersonaCard[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<BubbleMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const selected = useMemo(
    () => cards.find((c) => c.id === selectedId) || null,
    [cards, selectedId],
  );

  const sessionId = useMemo(() => {
    if (!selectedId || !userLocalId) return "";
    return soloSessionId(selectedId, userLocalId);
  }, [selectedId, userLocalId]);

  const personaMap = useMemo(() => {
    const m: Record<string, PersonaCard> = {};
    for (const c of cards) m[c.id] = c;
    return m;
  }, [cards]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const list = await listPersonas();
        if (cancelled) return;
        setCards(list);
        const saved = localStorage.getItem(SELECTED_KEY);
        if (saved && list.some((c) => c.id === saved)) setSelectedId(saved);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sessionId || !selectedId) {
      setMessages([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const turns = await fetchHistory(sessionId);
        if (cancelled) return;
        const bubbles: BubbleMessage[] = [];
        for (const t of turns) {
          if (t.user) bubbles.push({ id: uid(), role: "user", content: t.user });
          if (t.assistant) {
            bubbles.push({
              id: uid(),
              role: "assistant",
              content: t.assistant,
              personaId: selectedId,
            });
          }
        }
        if (bubbles.length === 0 && selected?.greeting) {
          bubbles.push({
            id: uid(),
            role: "assistant",
            content: selected.greeting,
            personaId: selectedId,
          });
        }
        setMessages(bubbles);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, selectedId, selected?.greeting]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const pickPersona = useCallback((card: PersonaCard) => {
    setSelectedId(card.id);
    localStorage.setItem(SELECTED_KEY, card.id);
    setError(null);
  }, []);

  const onSend = async () => {
    const raw = text.trim();
    if (!raw || busy || !selectedId || !sessionId) return;
    setBusy(true);
    setError(null);
    setText("");
    const pendingId = uid();
    setMessages((prev) => [
      ...prev,
      { id: uid(), role: "user", content: raw },
      { id: pendingId, role: "assistant", content: "", personaId: selectedId, pending: true },
    ]);
    try {
      let acc = "";
      const { reply, meta } = await streamChat({
        text: raw,
        sessionId,
        forcedPersona: selectedId,
        stripPersonaPrefix: true,
        onDelta: (chunk) => {
          acc += chunk;
          setMessages((prev) =>
            prev.map((m) => (m.id === pendingId ? { ...m, content: acc, pending: true } : m)),
          );
        },
      });
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? {
                ...m,
                content: reply || acc,
                personaId: meta?.active_persona || selectedId || parsePersonaFromReply(reply),
                pending: false,
              }
            : m,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setMessages((prev) => prev.filter((m) => m.id !== pendingId));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppShell
      subtitle={selected ? `与 ${selected.name} 密谈` : "选择谈话对象"}
      actions={
        sessionId ? (
          <span className="hidden text-xs text-[var(--ax-muted)] lg:inline">{sessionId}</span>
        ) : null
      }
    >
      <div className="ax-stage flex min-h-0 flex-1 flex-col gap-4 md:flex-row">
        <aside className="ax-roster flex w-full flex-col gap-2 md:w-64 lg:w-72">
          <h2 className="px-1 text-xs font-medium uppercase tracking-wider text-[var(--ax-muted)]">
            选择角色卡
          </h2>
          <div className="space-y-2 overflow-y-auto">
            {cards.map((c) => (
              <PersonaCardTile
                key={c.id}
                card={c}
                compact
                selected={c.id === selectedId}
                onSelect={pickPersona}
              />
            ))}
          </div>
        </aside>

        <section className="ax-chat-panel flex min-h-[70vh] flex-1 flex-col overflow-hidden">
          {!selectedId ? (
            <div className="ax-empty flex flex-1 flex-col items-center justify-center gap-2 text-center">
              <p className="font-[family-name:var(--font-display)] text-2xl tracking-wide">
                单人谈话
              </p>
              <p className="max-w-sm text-sm text-[var(--ax-muted)]">
                从左侧选择一位内阁成员；会话与群聊记忆隔离。
              </p>
            </div>
          ) : (
            <>
              <MessageList
                messages={messages}
                personaMap={personaMap}
                emptyTitle={selected?.name || "单人谈话"}
                emptyHint={selected?.personality || "开始对话。"}
              />
              <div ref={bottomRef} />
              {error ? <p className="px-2 text-sm text-red-600">{error}</p> : null}
              <div className="border-t border-[var(--ax-line)] p-3">
                <div className="flex flex-col gap-2">
                  <textarea
                    className="ax-input min-h-[72px] w-full resize-y"
                    placeholder={`对 ${selected?.name || ""} 说…`}
                    value={text}
                    disabled={busy}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void onSend();
                      }
                    }}
                  />
                  <button
                    type="button"
                    className="ax-btn-primary self-start"
                    disabled={busy || !text.trim()}
                    onClick={() => void onSend()}
                  >
                    发送
                  </button>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </AppShell>
  );
}
