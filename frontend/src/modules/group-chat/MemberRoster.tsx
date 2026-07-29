"use client";

import type { PersonaCard } from "@/matrix/types";
import { PersonaAvatar } from "@/modules/persona-cards/PersonaAvatar";

export function MemberRoster({
  cards,
  presentIds,
  nominatedId,
  onTogglePresent,
  onNominate,
}: {
  cards: PersonaCard[];
  presentIds: Set<string>;
  nominatedId: string | null;
  onTogglePresent: (id: string) => void;
  onNominate: (id: string | null) => void;
}) {
  return (
    <aside className="ax-roster flex w-full flex-col gap-2 md:w-56 lg:w-64">
      <div className="flex items-center justify-between px-1">
        <h2 className="text-xs font-medium uppercase tracking-wider text-[var(--ax-muted)]">在场成员</h2>
        <button
          type="button"
          className="text-xs text-[var(--ax-muted)] hover:text-[var(--ax-fg)]"
          onClick={() => onNominate(null)}
        >
          清除点名
        </button>
      </div>
      <ul className="space-y-1 overflow-y-auto">
        {cards.map((c) => {
          const present = presentIds.has(c.id);
          const nominated = nominatedId === c.id;
          return (
            <li key={c.id}>
              <div
                className={`flex items-center gap-2 rounded-xl border px-2 py-1.5 transition ${
                  nominated
                    ? "border-[var(--ax-accent)] bg-[var(--ax-accent)]/10"
                    : "border-transparent hover:border-[var(--ax-line)] hover:bg-[var(--ax-panel)]"
                }`}
              >
                <input
                  type="checkbox"
                  checked={present}
                  onChange={() => onTogglePresent(c.id)}
                  className="accent-[var(--ax-accent)]"
                  title="在场"
                  aria-label={`${c.name} 在场`}
                />
                <button
                  type="button"
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                  onClick={() => onNominate(nominated ? null : c.id)}
                  title="点名发言"
                >
                  <PersonaAvatar persona={c} size={28} />
                  <span className="truncate text-sm">
                    <span className="font-medium">{c.name}</span>
                    <span className="ml-1 text-xs text-[var(--ax-muted)]">{c.title}</span>
                  </span>
                </button>
              </div>
            </li>
          );
        })}
      </ul>
      {nominatedId ? (
        <p className="px-1 text-xs text-[var(--ax-muted)]">
          本轮点名：<span className="text-[var(--ax-fg)]">{nominatedId}</span>
        </p>
      ) : (
        <p className="px-1 text-xs text-[var(--ax-muted)]">未点名时由路由自动选人</p>
      )}
    </aside>
  );
}
