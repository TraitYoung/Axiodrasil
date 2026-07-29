"use client";

import type { PersonaCard } from "@/matrix/types";
import { PersonaAvatar } from "./PersonaAvatar";

export function PersonaCardTile({
  card,
  selected,
  onSelect,
  compact,
}: {
  card: PersonaCard;
  selected?: boolean;
  onSelect?: (card: PersonaCard) => void;
  compact?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={() => onSelect?.(card)}
      className={`ax-card-tile w-full text-left transition ${
        selected ? "ring-2 ring-[var(--ax-accent)]" : "hover:border-[var(--ax-accent)]/50"
      }`}
      style={{ borderColor: selected ? card.color : undefined }}
    >
      <div className="flex items-start gap-3">
        <PersonaAvatar persona={card} size={compact ? 32 : 40} />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="truncate font-medium text-[var(--ax-fg)]">{card.name}</span>
            <span className="truncate text-xs text-[var(--ax-muted)]">{card.title}</span>
          </div>
          {!compact && card.personality ? (
            <p className="mt-1 line-clamp-2 text-xs leading-relaxed text-[var(--ax-muted)]">
              {card.personality}
            </p>
          ) : null}
        </div>
      </div>
    </button>
  );
}

export function PersonaCardDrawer({
  open,
  cards,
  onClose,
  onPick,
  title = "角色卡",
}: {
  open: boolean;
  cards: PersonaCard[];
  onClose: () => void;
  onPick?: (card: PersonaCard) => void;
  title?: string;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/40" onClick={onClose}>
      <aside
        className="ax-drawer flex h-full w-full max-w-md flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-[var(--ax-line)] px-4 py-3">
          <h2 className="font-[family-name:var(--font-display)] text-lg tracking-wide">{title}</h2>
          <button type="button" className="ax-btn-ghost" onClick={onClose}>
            关闭
          </button>
        </div>
        <div className="flex-1 space-y-2 overflow-y-auto p-4">
          {cards.map((c) => (
            <PersonaCardTile
              key={c.id}
              card={c}
              onSelect={(card) => {
                onPick?.(card);
                onClose();
              }}
            />
          ))}
        </div>
      </aside>
    </div>
  );
}
