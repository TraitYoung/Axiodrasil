import { NextResponse } from "next/server";
import { getBackendBaseUrl } from "@/infra/backend";

export const runtime = "nodejs";

export async function GET() {
  const backendUrl = `${getBackendBaseUrl()}/api/v1/personas`;
  try {
    const res = await fetch(backendUrl, { cache: "no-store" });
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
