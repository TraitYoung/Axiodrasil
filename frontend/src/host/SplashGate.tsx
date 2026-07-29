"use client";

import { useEffect, useState, type ReactNode } from "react";

const SPLASH_KEY = "ax-splash-seen";
const AUTO_ENTER_MS = 1200;

export function SplashGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const [showSplash, setShowSplash] = useState(true);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    try {
      if (sessionStorage.getItem(SPLASH_KEY) === "1") {
        setShowSplash(false);
      }
    } catch {
      // private mode / blocked storage → still show once this mount
    }
    setReady(true);
  }, []);

  useEffect(() => {
    if (!ready || !showSplash) return;
    const t = window.setTimeout(() => enter(), AUTO_ENTER_MS);
    return () => window.clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, showSplash]);

  function enter() {
    if (leaving || !showSplash) return;
    setLeaving(true);
    try {
      sessionStorage.setItem(SPLASH_KEY, "1");
    } catch {
      /* ignore */
    }
    window.setTimeout(() => setShowSplash(false), 380);
  }

  if (!ready) {
    return <div className="ax-splash-boot" aria-hidden />;
  }

  if (!showSplash) {
    return <>{children}</>;
  }

  return (
    <div className={`ax-splash ${leaving ? "ax-splash--leave" : ""}`} role="dialog" aria-label="Axiodrasil 开屏">
      <div className="ax-splash-glow" aria-hidden />
      <p className="ax-splash-eyebrow">Imperial Cabinet</p>
      <h1 className="ax-splash-brand">Axiodrasil</h1>
      <p className="ax-splash-tagline">高压场景下的内阁议事与记忆内核</p>
      <button type="button" className="ax-splash-cta" onClick={enter}>
        进入议事厅
      </button>
    </div>
  );
}
