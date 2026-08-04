import type { NextRequest } from "next/server";
import { NextResponse } from "next/server";
import { getBackendBaseUrl } from "@/infra/backend";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  let body: unknown;
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ detail: "invalid json" }, { status: 400 });
  }

  const backendUrl = `${getBackendBaseUrl()}/api/v1/presence`;
  let backendRes: Response;
  try {
    backendRes = await fetch(backendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(15_000),
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return NextResponse.json(
      { detail: `无法连接 FastAPI（${backendUrl}）：${msg}` },
      { status: 503 },
    );
  }

  const text = await backendRes.text().catch(() => "");
  if (!backendRes.ok) {
    return NextResponse.json(
      { detail: "backend presence failed", status: backendRes.status, text },
      { status: backendRes.status >= 400 && backendRes.status < 600 ? backendRes.status : 500 },
    );
  }
  try {
    return NextResponse.json(JSON.parse(text));
  } catch {
    return NextResponse.json({ detail: "invalid json from backend", text }, { status: 500 });
  }
}
