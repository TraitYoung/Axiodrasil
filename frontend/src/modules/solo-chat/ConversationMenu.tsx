"use client";

import { useEffect, useRef, useState } from "react";
import type { SoloConversation } from "./conversationStore";

/** 邻舍式会话抽屉：列表 + 新建 / 重命名 / 删除 */
export function ConversationMenu({
  items,
  activeId,
  disabled,
  onCreate,
  onSelect,
  onRename,
  onRemove,
}: {
  items: SoloConversation[];
  activeId: string;
  disabled?: boolean;
  onCreate: () => void;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onRemove: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const active = items.find((x) => x.id === activeId) || items[0];

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  return (
    <div className="ax-convo-menu relative" ref={rootRef}>
      <button
        type="button"
        className="ax-btn-ghost max-w-[12rem] truncate sm:max-w-[16rem]"
        disabled={disabled}
        title="谈话列表"
        onClick={() => setOpen((v) => !v)}
      >
        谈话 · {active?.title || "…"}
      </button>
      {open ? (
        <div className="ax-convo-panel absolute right-0 top-full z-30 mt-2 w-[min(20rem,calc(100vw-2rem))] overflow-hidden rounded-xl border border-[var(--ax-line)] bg-[var(--ax-panel)] shadow-lg">
          <div className="flex items-center justify-between gap-2 border-b border-[var(--ax-line)] px-3 py-2">
            <p className="text-xs text-[var(--ax-muted)]">记忆互通 · 各谈话共享私忆</p>
            <button
              type="button"
              className="ax-btn-primary px-3 py-1 text-xs"
              disabled={disabled}
              onClick={() => {
                onCreate();
                setOpen(false);
              }}
            >
              新建谈话
            </button>
          </div>
          <ul className="max-h-72 overflow-y-auto py-1">
            {items.map((item) => {
              const selected = item.id === activeId;
              return (
                <li key={item.id}>
                  <div
                    className={`group flex items-start gap-2 px-3 py-2 ${
                      selected ? "bg-[rgba(198,169,240,0.12)]" : "hover:bg-[rgba(198,169,240,0.06)]"
                    }`}
                  >
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      disabled={disabled}
                      onClick={() => {
                        onSelect(item.id);
                        setOpen(false);
                      }}
                    >
                      <p className="truncate text-sm text-[var(--ax-fg)]">{item.title}</p>
                      <p className="truncate text-xs text-[var(--ax-muted)]">
                        {item.preview || "还没有往来…"}
                      </p>
                    </button>
                    <div className="flex shrink-0 flex-col gap-1 opacity-80 group-hover:opacity-100">
                      <button
                        type="button"
                        className="text-[10px] text-[var(--ax-muted)] hover:text-[var(--ax-fg)]"
                        disabled={disabled}
                        onClick={() => {
                          const next = window.prompt("给这次谈话起个名字", item.title);
                          if (next != null) onRename(item.id, next);
                        }}
                      >
                        改名
                      </button>
                      <button
                        type="button"
                        className="text-[10px] text-red-400/80 hover:text-red-400"
                        disabled={disabled}
                        onClick={() => {
                          if (window.confirm(`结束「${item.title}」？气泡会清掉，共享记忆还在。`)) {
                            onRemove(item.id);
                          }
                        }}
                      >
                        结束
                      </button>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
