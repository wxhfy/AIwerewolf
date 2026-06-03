import { NextRequest, NextResponse } from "next/server";

/**
 * Proxy POST /api/rooms/:id/action to the backend.
 * Next.js rewrites() in dev mode can drop POST body — this middleware
 * runs earlier and forwards the raw body correctly.
 */
export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const actionMatch = pathname.match(/^\/api\/rooms\/(.+)\/action$/);

  if (actionMatch && request.method === "POST") {
    const roomId = actionMatch[1];
    const backend = process.env.BACKEND_ORIGIN || "http://localhost:3009";
    const body = await request.text();

    try {
      const resp = await fetch(`${backend}/api/rooms/${roomId}/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
      });
      const data = await resp.json();
      return NextResponse.json(data, { status: resp.status });
    } catch (e: any) {
      return NextResponse.json({ error: e?.message || "Proxy error" }, { status: 502 });
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: "/api/rooms/:path*/action",
};
