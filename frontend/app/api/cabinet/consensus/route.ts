import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { getBackendBaseUrl } from "@/infra/backend";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const sessionId = req.headers.get("x-session-id") || undefined;
  if (!sessionId) {
    return NextResponse.json({ detail: "missing x-session-id" }, { status: 400 });
  }
  const backendUrl = `${getBackendBaseUrl()}/api/v1/cabinet/consensus`;
  try {
    const res = await fetch(backendUrl, {
      method: "POST",
      headers: { "x-session-id": sessionId },
    });
    const text = await res.text();
    return new NextResponse(text, {
      status: res.status,
      headers: { "Content-Type": "application/json; charset=utf-8" },
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json({ detail: msg }, { status: 503 });
  }
}
