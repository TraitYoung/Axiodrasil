"use client";

import { useEffect, useState } from "react";

const LOAD_LINES = [
  "Bina 正在系鞋带…",
  "把茶泡上，马上就来。",
  "电波对准中，别走开。",
  "偷偷整理一下表情…",
  "嗯，找到陛下了。",
] as const;

const THINK_LINES = [
  "悄悄想一下…",
  "揉揉脑袋中…",
  "斟酌措辞中…",
  "再确认一遍心意…",
] as const;

const ERROR_LINE = ["出了点小状况…"] as const;

export function useRotatingLine(lines: readonly string[], intervalMs = 2200): string {
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    if (lines.length <= 1) return;
    const id = window.setInterval(() => {
      setIdx((i) => (i + 1) % lines.length);
    }, intervalMs);
    return () => window.clearInterval(id);
  }, [lines, intervalMs]);
  return lines[idx] || lines[0] || "";
}

export function CuteWait({
  mode = "load",
  error,
  onRetry,
}: {
  mode?: "load" | "think";
  error?: string | null;
  onRetry?: () => void;
}) {
  const lines = mode === "think" ? THINK_LINES : LOAD_LINES;
  const line = useRotatingLine(error ? ERROR_LINE : lines);

  return (
    <div className="ax-cute-wait flex flex-col items-center justify-center gap-4 text-center">
      <div className="ax-cute-orb" aria-hidden="true">
        <span className="ax-cute-orb__ring" />
        <span className="ax-cute-orb__ring ax-cute-orb__ring--delay" />
        <span className="ax-cute-orb__core">B</span>
      </div>
      <div className="min-h-[3rem] space-y-1">
        <p
          key={line}
          className="ax-cute-line font-[family-name:var(--font-display)] text-xl tracking-wide text-[var(--ax-fg)]"
        >
          {line}
        </p>
        {!error ? (
          <p className="text-xs text-[var(--ax-muted)]">
            {mode === "think" ? "她在认真听你说话" : "首席私人秘书接通中"}
          </p>
        ) : (
          <p className="max-w-sm text-xs leading-relaxed text-red-400">{error}</p>
        )}
      </div>
      {error && onRetry ? (
        <button type="button" className="ax-btn-ghost" onClick={onRetry}>
          重新接通
        </button>
      ) : null}
    </div>
  );
}

export { LOAD_LINES, THINK_LINES };
