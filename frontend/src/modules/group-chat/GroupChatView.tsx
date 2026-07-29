"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/host/AppShell";
import {
  cabinetConsensus,
  fetchHistory,
  listPersonas,
  parsePersonaFromReply,
  streamChat,
} from "@/matrix/client";
import { GROUP_SESSION_ID, type PersonaCard } from "@/matrix/types";
import { PersonaCardDrawer } from "@/modules/persona-cards/PersonaCardTile";
import { MemberRoster } from "./MemberRoster";
import { MessageList, type BubbleMessage } from "./MessageList";

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function parseAtMention(text: string, cards: PersonaCard[]): { clean: string; persona: string | null } {
  const re = /@([^\s@]+)/;
  const m = text.match(re);
  if (!m) return { clean: text, persona: null };
  const token = m[1].trim().toLowerCase();
  const hit = cards.find(
    (c) =>
      c.id === token ||
      c.name.toLowerCase() === token ||
      c.name.includes(m[1]) ||
      c.title.includes(m[1]),
  );
  if (!hit) return { clean: text, persona: null };
  return { clean: text.replace(re, "").trim() || text, persona: hit.id };
}

export function GroupChatView() {
  const [cards, setCards] = useState<PersonaCard[]>([]);
  const [presentIds, setPresentIds] = useState<Set<string>>(new Set());
  const [nominatedId, setNominatedId] = useState<string | null>(null);
  const [messages, setMessages] = useState<BubbleMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [status, setStatus] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const sessionId = GROUP_SESSION_ID;

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
        setPresentIds(new Set(list.map((c) => c.id)));
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
              personaId: t.persona || parsePersonaFromReply(t.assistant) || undefined,
            });
          }
        }
        setMessages(bubbles);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const togglePresent = useCallback((id: string) => {
    setPresentIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const sendOnce = useCallback(
    async (userText: string, forced: string | null) => {
      const userMsg: BubbleMessage = { id: uid(), role: "user", content: userText };
      const pendingId = uid();
      setMessages((prev) => [
        ...prev,
        userMsg,
        { id: pendingId, role: "assistant", content: "", personaId: forced || undefined, pending: true },
      ]);

      let acc = "";
      const { reply, meta } = await streamChat({
        text: userText,
        sessionId,
        forcedPersona: forced,
        stripPersonaPrefix: Boolean(forced),
        onDelta: (chunk) => {
          acc += chunk;
          setMessages((prev) =>
            prev.map((m) => (m.id === pendingId ? { ...m, content: acc, pending: true } : m)),
          );
        },
      });

      const personaId =
        meta?.active_persona || forced || parsePersonaFromReply(reply) || undefined;
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? {
                ...m,
                content: reply || acc,
                personaId,
                pending: false,
              }
            : m,
        ),
      );
      return personaId;
    },
    [sessionId],
  );

  const onSend = async () => {
    const raw = text.trim();
    if (!raw || busy) return;
    setBusy(true);
    setError(null);
    setText("");
    try {
      const at = parseAtMention(raw, cards);
      const forced = nominatedId || at.persona;
      await sendOnce(at.clean, forced);
      setNominatedId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onRelayPresent = async () => {
    const raw = text.trim();
    if (!raw || busy) return;
    const present = cards.filter((c) => presentIds.has(c.id));
    if (present.length === 0) {
      setError("请至少勾选一位在场成员");
      return;
    }
    setBusy(true);
    setError(null);
    setText("");
    try {
      for (const c of present) {
        setStatus(`传令 ${c.name}…`);
        await sendOnce(raw, c.id);
      }
      setStatus("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      setStatus("");
    }
  };

  const onConsensus = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await cabinetConsensus(sessionId);
      setStatus(res.message + (res.summary ? `：${res.summary.slice(0, 80)}` : ""));
      setMessages((prev) => [
        ...prev,
        {
          id: uid(),
          role: "assistant",
          content: res.summary
            ? `【共识】${res.summary}`
            : res.message,
          personaId: "jean",
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <AppShell
      subtitle={`会话 ${sessionId}`}
      actions={
        <>
          <button type="button" className="ax-btn-ghost" onClick={() => setDrawerOpen(true)}>
            角色卡
          </button>
          <button type="button" className="ax-btn-ghost" disabled={busy} onClick={onConsensus}>
            散会
          </button>
        </>
      }
    >
      <div className="ax-stage flex min-h-0 flex-1 flex-col gap-4 md:flex-row">
        <MemberRoster
          cards={cards}
          presentIds={presentIds}
          nominatedId={nominatedId}
          onTogglePresent={togglePresent}
          onNominate={setNominatedId}
        />
        <section className="ax-chat-panel flex min-h-[70vh] flex-1 flex-col overflow-hidden">
          <MessageList messages={messages} personaMap={personaMap} />
          <div ref={bottomRef} />
          {error ? <p className="px-2 text-sm text-red-600">{error}</p> : null}
          {status ? <p className="px-2 text-xs text-[var(--ax-muted)]">{status}</p> : null}
          <div className="border-t border-[var(--ax-line)] p-3">
            <div className="flex flex-col gap-2">
              <textarea
                className="ax-input min-h-[72px] w-full resize-y"
                placeholder="输入议题… 可用 @Bina / @郅政 点名；勾选成员后可「传令在场」"
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
              <div className="flex flex-wrap items-center gap-2">
                <button type="button" className="ax-btn-primary" disabled={busy || !text.trim()} onClick={() => void onSend()}>
                  发送
                </button>
                <button
                  type="button"
                  className="ax-btn-ghost"
                  disabled={busy || !text.trim()}
                  onClick={() => void onRelayPresent()}
                >
                  传令在场依次发言
                </button>
                {nominatedId ? (
                  <span className="text-xs text-[var(--ax-muted)]">
                    点名 {personaMap[nominatedId]?.name || nominatedId}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        </section>
      </div>
      <PersonaCardDrawer
        open={drawerOpen}
        cards={cards}
        onClose={() => setDrawerOpen(false)}
        onPick={(c) => setNominatedId(c.id)}
        title="角色卡 · 点选即点名"
      />
    </AppShell>
  );
}
