"use client";

import type { PersonaCard } from "@/matrix/types";

export function PersonaAvatar({
  persona,
  size = 36,
}: {
  persona?: Pick<PersonaCard, "id" | "name" | "color"> | null;
  size?: number;
}) {
  const letter = (persona?.name || persona?.id || "?").slice(0, 1).toUpperCase();
  const color = persona?.color || "#8b7355";
  return (
    <div
      className="flex shrink-0 items-center justify-center rounded-full font-semibold text-white shadow-sm"
      style={{
        width: size,
        height: size,
        fontSize: size * 0.4,
        background: `linear-gradient(145deg, ${color}, ${color}aa)`,
      }}
      title={persona?.name || persona?.id}
    >
      {letter}
    </div>
  );
}
