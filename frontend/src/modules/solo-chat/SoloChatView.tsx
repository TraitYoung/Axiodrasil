"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/host/AppShell";
import { useUserLocalId } from "@/infra/session";
import {
  fetchHistory,
  getPersona,
  parsePersonaFromReply,
  streamChat,
} from "@/matrix/client";
import { soloSessionId, type PersonaCard } from "@/matrix/types";
import { PersonaAvatar } from "@/modules/persona-cards/PersonaAvatar";
import { MessageList, type BubbleMessage } from "@/modules/group-chat/MessageList";

const BINA_ID = "bina";

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function SoloChatView() {
  const userLocalId = useUserLocalId();
  const [card, setCard] = useState<PersonaCard | null>(null);
  const [messages, setMessages] = useState<BubbleMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const sessionId = useMemo(() => {
    if (!userLocalId) return "";
    return soloSessionId(BINA_ID, userLocalId);
  }, [userLocalId]);

  const personaMap = useMemo(() => {
    if (!card) return {};
    return { [card.id]: card };
  }, [card]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const bina = await getPersona(BINA_ID);
        if (!cancelled) setCard(bina);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sessionId || !card) {
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
              personaId: BINA_ID,
            });
          }
        }
        if (bubbles.length === 0 && card.greeting) {
          bubbles.push({
            id: uid(),
            role: "assistant",
            content: card.greeting,
            personaId: BINA_ID,
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
  }, [sessionId, card]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const onSend = async () => {
    const raw = text.trim();
    if (!raw || busy || !sessionId) return;
    setBusy(true);
    setError(null);
    setText("");
    const pendingId = uid();
    setMessages((prev) => [
      ...prev,
      { id: uid(), role: "user", content: raw },
      { id: pendingId, role: "assistant", content: "", personaId: BINA_ID, pending: true },
    ]);
    try {
      let acc = "";
      const { reply, meta } = await streamChat({
        text: raw,
        sessionId,
        forcedPersona: BINA_ID,
        stripPersonaPrefix: true,
        groupMode: false,
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
                personaId: meta?.active_persona || BINA_ID || parsePersonaFromReply(reply),
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
      subtitle={card ? `与 ${card.name} 密谈` : "Bina 单人谈话"}
      actions={
        sessionId ? (
          <span className="hidden text-xs text-[var(--ax-muted)] lg:inline">{sessionId}</span>
        ) : null
      }
    >
      <div className="ax-stage flex min-h-0 flex-1 flex-col gap-4 md:flex-row">
        <aside className="ax-roster flex w-full flex-col gap-3 md:w-64 lg:w-72">
          <h2 className="px-1 text-xs font-medium uppercase tracking-wider text-[var(--ax-muted)]">
            谈话对象
          </h2>
          {card ? (
            <div className="ax-card-tile space-y-3 p-3">
              <div className="flex items-start gap-3">
                <PersonaAvatar persona={card} size={48} />
                <div className="min-w-0">
                  <p className="font-medium text-[var(--ax-fg)]">{card.name}</p>
                  <p className="text-xs text-[var(--ax-muted)]">{card.title}</p>
                </div>
              </div>
              {card.personality ? (
                <p className="text-xs leading-relaxed text-[var(--ax-muted)]">{card.personality}</p>
              ) : null}
              <p className="text-xs leading-relaxed text-[var(--ax-muted)]">
                当前全力开发 Bina 单聊；其他内阁成员已从公开入口软归档，会话与群聊记忆隔离。
              </p>
            </div>
          ) : (
            <p className="px-1 text-sm text-[var(--ax-muted)]">正在加载 Bina…</p>
          )}
        </aside>

        <section className="ax-chat-panel flex min-h-[70vh] flex-1 flex-col overflow-hidden">
          {!card ? (
            <div className="ax-empty flex flex-1 flex-col items-center justify-center gap-2 text-center">
              <p className="font-[family-name:var(--font-display)] text-2xl tracking-wide">
                Bina 单人谈话
              </p>
              <p className="max-w-sm text-sm text-[var(--ax-muted)]">正在接通首席私人秘书…</p>
            </div>
          ) : (
            <>
              <MessageList
                messages={messages}
                personaMap={personaMap}
                emptyTitle={card.name}
                emptyHint={card.personality || "先共情，再讲理。直接说就好。"}
              />
              <div ref={bottomRef} />
              {error ? <p className="px-2 text-sm text-red-600">{error}</p> : null}
              <div className="border-t border-[var(--ax-line)] p-3">
                <div className="flex flex-col gap-2">
                  <textarea
                    className="ax-input min-h-[72px] w-full resize-y"
                    placeholder="对 Bina 说… 吐槽、撒娇、汇报状态都行"
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
