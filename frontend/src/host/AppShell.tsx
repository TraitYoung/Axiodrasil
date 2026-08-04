"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const NAV = [{ href: "/solo", label: "Bina" }] as const;

export function AppShell({
  children,
  subtitle,
  actions,
}: {
  children: ReactNode;
  subtitle?: string;
  actions?: ReactNode;
}) {
  const pathname = usePathname();

  return (
    <div className="ax-shell min-h-screen flex flex-col">
      <header className="ax-header sticky top-0 z-20 border-b border-[var(--ax-line)] backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
          <Link href="/solo" className="ax-brand shrink-0">
            <span className="ax-brand-mark">Axiodrasil</span>
            <span className="ax-brand-sub">Bina</span>
          </Link>
          <nav className="flex items-center gap-1 rounded-full border border-[var(--ax-line)] bg-[var(--ax-panel)] p-1">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`ax-nav-pill rounded-full px-4 py-1.5 text-sm transition ${
                    active ? "ax-nav-pill--active" : "text-[var(--ax-muted)] hover:text-[var(--ax-fg)]"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          {subtitle ? (
            <p className="hidden text-sm text-[var(--ax-muted)] md:block">{subtitle}</p>
          ) : null}
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        </div>
      </header>
      <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col px-4 py-4">{children}</main>
    </div>
  );
}
