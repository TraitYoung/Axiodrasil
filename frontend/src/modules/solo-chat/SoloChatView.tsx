"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AppShell } from "@/host/AppShell";
import { useUserLocalId } from "@/infra/session";
import {
  fetchHistory,
  getPersona,
  ingestAttachment,
  parsePersonaFromReply,
  reportPresence,
  sendChat,
} from "@/matrix/client";
import type { ChatTurn, PersonaCard } from "@/matrix/types";
import { PersonaAvatar } from "@/modules/persona-cards/PersonaAvatar";
import { MessageList, type BubbleMessage } from "@/modules/group-chat/MessageList";
import { CuteWait, THINK_LINES, useRotatingLine } from "@/modules/solo-chat/CuteWait";
import { ConversationMenu } from "@/modules/solo-chat/ConversationMenu";
import {
  canSendChat,
  composeChatPayload,
  type PendingAttachment,
} from "@/modules/solo-chat/composePayload";
import { useSpeechInput } from "@/modules/solo-chat/useSpeechInput";
import {
  createConversation,
  ensureCatalog,
  getActiveConversation,
  listConversations,
  memoryPoolId,
  removeConversation,
  renameConversation,
  selectConversation,
  touchConversation,
  type SoloConversation,
} from "@/modules/solo-chat/conversationStore";

const FILE_ACCEPT =
  ".txt,.md,.markdown,.json,.csv,.log,image/png,image/jpeg,image/webp,image/gif";

const BINA_ID = "bina";
const PROACTIVE_MARKER = "[proactive]";

function uid() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function turnsToBubbles(turns: ChatTurn[], greeting?: string): BubbleMessage[] {
  const bubbles: BubbleMessage[] = [];
  for (const t of turns) {
    const isProactive = (t.user || "").trim() === PROACTIVE_MARKER;
    if (t.user && !isProactive) {
      bubbles.push({ id: uid(), role: "user", content: t.user });
    }
    if (t.assistant) {
      bubbles.push({
        id: uid(),
        role: "assistant",
        content: t.assistant,
        personaId: BINA_ID,
        hint: isProactive ? "Bina 先开口" : undefined,
      });
    }
  }
  if (bubbles.length === 0 && greeting) {
    bubbles.push({
      id: uid(),
      role: "assistant",
      content: greeting,
      personaId: BINA_ID,
    });
  }
  return bubbles;
}

export function SoloChatView() {
  const userLocalId = useUserLocalId();
  const [card, setCard] = useState<PersonaCard | null>(null);
  const [messages, setMessages] = useState<BubbleMessage[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [convos, setConvos] = useState<SoloConversation[]>([]);
  const [activeConvoId, setActiveConvoId] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const [interimSpeech, setInterimSpeech] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pendingLabel = useRotatingLine(THINK_LINES, 2400);

  const speech = useSpeechInput({
    sessionId: activeConvoId || undefined,
    onTranscript: (chunk, opts) => {
      if (opts?.replaceInterim) {
        setInterimSpeech(chunk);
        return;
      }
      setInterimSpeech("");
      setText((prev) => {
        const base = prev.trimEnd();
        const piece = chunk.trim();
        if (!piece) return prev;
        return base ? `${base}${/[。！？…]$/.test(base) ? "" : " "}${piece}` : piece;
      });
    },
    onError: (msg) => setError(msg),
  });

  const memoryThreadId = useMemo(() => {
    if (!userLocalId) return "";
    return memoryPoolId(userLocalId);
  }, [userLocalId]);

  /** 当前谈话气泡 session（可新建多条） */
  const sessionId = activeConvoId;

  const personaMap = useMemo(() => {
    if (!card) return {};
    return { [card.id]: card };
  }, [card]);

  const refreshCatalog = useCallback(() => {
    if (!userLocalId) return;
    ensureCatalog(userLocalId);
    setConvos(listConversations(userLocalId));
    setActiveConvoId(getActiveConversation(userLocalId).id);
  }, [userLocalId]);

  useEffect(() => {
    if (!userLocalId) return;
    refreshCatalog();
  }, [userLocalId, refreshCatalog]);

  const syncPresence = useCallback(
    async (sid: string) => {
      if (!memoryThreadId) return;
      try {
        await reportPresence(sid, memoryThreadId);
      } catch {
        // 后端未起时不阻断聊天
      }
    },
    [memoryThreadId],
  );

  const reloadHistory = useCallback(async (sid: string, greeting?: string) => {
    try {
      const turns = await fetchHistory(sid);
      setMessages(turnsToBubbles(turns, greeting));
    } catch {
      setMessages((prev) => (prev.length ? prev : turnsToBubbles([], greeting)));
      throw new Error("历史记录暂时读不到，先聊着；可点「重新接通」再试。");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        setError(null);
        const bina = await getPersona(BINA_ID);
        if (!cancelled) setCard(bina);
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sessionId || !card) {
      setMessages([]);
      setHistoryLoading(false);
      return;
    }
    let cancelled = false;
    (async () => {
      setHistoryLoading(true);
      try {
        await syncPresence(sessionId);
        if (cancelled) return;
        await reloadHistory(sessionId, card.greeting);
        if (!cancelled) setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setHistoryLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [sessionId, card, syncPresence, reloadHistory]);

  useEffect(() => {
    if (!sessionId || !card) return;
    const onFocus = () => {
      void syncPresence(sessionId);
      void reloadHistory(sessionId).catch(() => {});
    };
    window.addEventListener("focus", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
    };
  }, [sessionId, card, syncPresence, reloadHistory]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  const reconnect = useCallback(async () => {
    if (reconnecting || busy) return;
    setReconnecting(true);
    setError(null);
    setHistoryLoading(true);
    try {
      const bina = await getPersona(BINA_ID);
      setCard(bina);
      if (sessionId) {
        await syncPresence(sessionId);
        await reloadHistory(sessionId, bina.greeting);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setHistoryLoading(false);
      setReconnecting(false);
    }
  }, [reconnecting, busy, sessionId, syncPresence, reloadHistory]);

  const onCreateConvo = () => {
    if (!userLocalId || busy) return;
    clearAttachments(attachments);
    setAttachments([]);
    createConversation(userLocalId, "新的谈话");
    refreshCatalog();
    setMessages([]);
    setError(null);
  };

  const onSelectConvo = (id: string) => {
    if (!userLocalId || busy || id === activeConvoId) return;
    clearAttachments(attachments);
    setAttachments([]);
    selectConversation(userLocalId, id);
    refreshCatalog();
    setError(null);
  };

  const onRenameConvo = (id: string, title: string) => {
    if (!userLocalId) return;
    renameConversation(userLocalId, id, title);
    refreshCatalog();
  };

  const onRemoveConvo = (id: string) => {
    if (!userLocalId || busy) return;
    removeConversation(userLocalId, id);
    refreshCatalog();
    setError(null);
  };

  const onStop = () => {
    abortRef.current?.abort();
    speech.stop();
  };

  const clearAttachments = useCallback((list: PendingAttachment[]) => {
    for (const a of list) {
      if (a.previewUrl) URL.revokeObjectURL(a.previewUrl);
    }
  }, []);

  useEffect(() => {
    return () => clearAttachments(attachments);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only revoke on unmount
  }, []);

  const removeAttachment = (id: string) => {
    setAttachments((prev) => {
      const target = prev.find((x) => x.id === id);
      if (target?.previewUrl) URL.revokeObjectURL(target.previewUrl);
      return prev.filter((x) => x.id !== id);
    });
  };

  const onPickFiles = async (files: FileList | null) => {
    if (!files?.length || !sessionId) return;
    setUploading(true);
    setError(null);
    try {
      for (const file of Array.from(files)) {
        const result = await ingestAttachment(file, sessionId);
        const previewUrl =
          result.kind === "image" ? URL.createObjectURL(file) : undefined;
        setAttachments((prev) => [
          ...prev,
          {
            id: uid(),
            name: result.name,
            kind: result.kind,
            text: result.text,
            truncated: result.truncated,
            previewUrl,
          },
        ]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  };

  const onSend = async () => {
    if (busy || uploading || !sessionId || !memoryThreadId || !userLocalId) return;
    const typed = [text.trim(), interimSpeech.trim()].filter(Boolean).join(" ");
    if (!canSendChat(typed, attachments)) return;
    speech.stop();
    setInterimSpeech("");
    const payload = composeChatPayload(typed, attachments);
    if (!payload) return;
    const bubbleAttachments = attachments.map((a) => ({
      name: a.name,
      kind: a.kind,
      previewUrl: a.previewUrl,
    }));
    const displayText =
      typed || (attachments.length ? `（${attachments.length} 个附件）` : "");

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const timeoutId = window.setTimeout(() => controller.abort(), 120_000);

    setBusy(true);
    setError(null);
    setText("");
    const sentAtt = attachments;
    setAttachments([]);
    void syncPresence(sessionId);
    const pendingId = uid();
    setMessages((prev) => [
      ...prev,
      {
        id: uid(),
        role: "user",
        content: displayText,
        attachments: bubbleAttachments,
      },
      { id: pendingId, role: "assistant", content: "", personaId: BINA_ID, pending: true },
    ]);
    try {
      const { reply, meta } = await sendChat({
        text: payload,
        sessionId,
        memoryThreadId,
        forcedPersona: BINA_ID,
        stripPersonaPrefix: true,
        groupMode: false,
        signal: controller.signal,
      });
      setMessages((prev) =>
        prev.map((m) =>
          m.id === pendingId
            ? {
                ...m,
                content: reply,
                personaId: meta?.active_persona || BINA_ID || parsePersonaFromReply(reply),
                pending: false,
              }
            : m,
        ),
      );
      touchConversation(userLocalId, sessionId, typed || sentAtt[0]?.name || "附件", {
        suggestTitleFromPreview: true,
      });
      refreshCatalog();
    } catch (e) {
      const aborted =
        (e instanceof DOMException && e.name === "AbortError") ||
        (e instanceof Error && e.name === "AbortError");
      if (aborted) {
        setError("已停止这一轮。想说什么再说一句就好。");
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
      setMessages((prev) => prev.filter((m) => m.id !== pendingId));
      // 失败时尽量把附件还回去（预览 URL 仍有效）
      setAttachments((prev) => (prev.length ? prev : sentAtt));
    } finally {
      window.clearTimeout(timeoutId);
      if (abortRef.current === controller) abortRef.current = null;
      setBusy(false);
    }
  };

  const statusHint = reconnecting
    ? "内线重拨中…"
    : historyLoading
      ? "翻找往来记录…"
      : null;

  return (
    <AppShell
      subtitle={card ? `与 ${card.name} 密谈` : "Bina 单人谈话"}
      actions={
        <>
          {userLocalId ? (
            <ConversationMenu
              items={convos}
              activeId={activeConvoId}
              disabled={busy || reconnecting}
              onCreate={onCreateConvo}
              onSelect={onSelectConvo}
              onRename={onRenameConvo}
              onRemove={onRemoveConvo}
            />
          ) : null}
          <button
            type="button"
            className="ax-btn-ghost"
            disabled={reconnecting || busy}
            title="重新拉取角色与消息，校准内线"
            onClick={() => void reconnect()}
          >
            {reconnecting ? "接通中…" : "重新接通"}
          </button>
        </>
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
                顶栏「谈话」可新建/切换气泡；各谈话记忆互通。托盘常驻时她也可能先开口。
              </p>
            </div>
          ) : (
            <div className="px-1 py-4">
              <CuteWait mode="load" error={error} onRetry={() => void reconnect()} />
            </div>
          )}
        </aside>

        <section className="ax-chat-panel flex min-h-[70vh] flex-1 flex-col overflow-hidden">
          {!card ? (
            <div className="ax-empty flex flex-1 flex-col items-center justify-center px-4">
              <CuteWait mode="load" error={error} onRetry={() => void reconnect()} />
            </div>
          ) : (
            <>
              <MessageList
                messages={messages}
                personaMap={personaMap}
                emptyTitle={card.name}
                emptyHint={
                  historyLoading
                    ? "正在翻找往来记录…"
                    : "新的谈话从空白开始；共享私忆还在。直接说就好。"
                }
                pendingLabel={busy ? pendingLabel : "悄悄想一下…"}
                statusHint={statusHint}
              />
              <div ref={bottomRef} />
              {error ? <p className="px-2 text-sm text-red-600">{error}</p> : null}
              <div className="border-t border-[var(--ax-line)] p-3">
                <div className="flex flex-col gap-2">
                  {attachments.length ? (
                    <ul className="flex flex-wrap gap-2">
                      {attachments.map((a) => (
                        <li
                          key={a.id}
                          className="flex max-w-full items-center gap-2 rounded-lg border border-[var(--ax-line)] bg-[var(--ax-panel)] px-2 py-1 text-xs"
                        >
                          {a.kind === "image" && a.previewUrl ? (
                            // eslint-disable-next-line @next/next/no-img-element
                            <img
                              src={a.previewUrl}
                              alt=""
                              className="h-8 w-8 rounded object-cover"
                            />
                          ) : null}
                          <span className="truncate">
                            {a.kind === "image" ? "图片" : "附件"} · {a.name}
                            {a.truncated ? "（已截断）" : ""}
                          </span>
                          <button
                            type="button"
                            className="text-[var(--ax-muted)] hover:text-[var(--ax-fg)]"
                            disabled={busy}
                            onClick={() => removeAttachment(a.id)}
                          >
                            移除
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : null}
                  <textarea
                    className="ax-input min-h-[72px] w-full resize-y"
                    placeholder="对 Bina 说… 也可上传文件/图片，或点麦克风说话"
                    value={interimSpeech ? `${text}${text && !/\s$/.test(text) ? " " : ""}${interimSpeech}` : text}
                    disabled={busy || !sessionId || speech.busy}
                    onChange={(e) => {
                      setInterimSpeech("");
                      setText(e.target.value);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        void onSend();
                      }
                    }}
                  />
                  <div className="flex flex-wrap items-center gap-2">
                    <input
                      ref={fileInputRef}
                      type="file"
                      className="hidden"
                      accept={FILE_ACCEPT}
                      multiple
                      onChange={(e) => void onPickFiles(e.target.files)}
                    />
                    <button
                      type="button"
                      className="ax-btn-ghost"
                      disabled={busy || uploading || !sessionId}
                      title="上传文本或图片"
                      onClick={() => fileInputRef.current?.click()}
                    >
                      {uploading ? "处理中…" : "附件"}
                    </button>
                    <button
                      type="button"
                      className="ax-btn-ghost"
                      disabled={busy || uploading || !sessionId || speech.busy}
                      title={
                        speech.webSpeechSupported
                          ? "浏览器听写（再点停止）"
                          : "录音后走服务端识别"
                      }
                      onClick={() => speech.toggle()}
                    >
                      {speech.mode === "listening"
                        ? "听写中…"
                        : speech.mode === "recording"
                          ? "录音中…"
                          : speech.mode === "transcribing"
                            ? "识别中…"
                            : "麦克风"}
                    </button>
                    {!speech.webSpeechSupported || speech.mode === "idle" ? (
                      <button
                        type="button"
                        className="ax-btn-ghost text-xs"
                        disabled={busy || uploading || !sessionId || speech.busy}
                        title="强制服务端 STT"
                        onClick={() => speech.toggleServer()}
                      >
                        {speech.mode === "recording" ? "结束录音" : "服务端识别"}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="ax-btn-primary self-start"
                      disabled={
                        busy ||
                        uploading ||
                        !sessionId ||
                        !canSendChat(text, attachments)
                      }
                      onClick={() => void onSend()}
                    >
                      发送
                    </button>
                    {busy || speech.active ? (
                      <button type="button" className="ax-btn-ghost" onClick={onStop}>
                        停止
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            </>
          )}
        </section>
      </div>
    </AppShell>
  );
}
