import { NextRequest, NextResponse } from "next/server";
import { COOKIE, validSession } from "../../session";
export const dynamic = "force-dynamic";
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  if (!validSession(request.cookies.get(COOKIE)?.value))
    return NextResponse.json(
      { detail: "Sign in to the ATLAS workspace." },
      { status: 401 },
    );
  const { path } = await context.params;
  if (path.some((p) => !/^[a-zA-Z0-9_-]+$/.test(p)))
    return NextResponse.json({ detail: "Invalid path" }, { status: 400 });
  if (request.method !== "GET") {
    const origin = request.headers.get("origin");
    if (!origin || new URL(origin).host !== request.headers.get("host"))
      return NextResponse.json(
        { detail: "Cross-origin operation blocked" },
        { status: 403 },
      );
    if (!process.env.AEGIS_CONTROL_TOKEN)
      return NextResponse.json(
        { detail: "Console is read-only; configure the operator token" },
        { status: 403 },
      );
  }
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    if (body && body.length > 65536)
      return NextResponse.json(
        { detail: "Request too large" },
        { status: 413 },
      );
    const upstream = await fetch(
      `${process.env.AEGIS_CONTROL_URL || "http://127.0.0.1:8100"}/api/v1/${path.join("/")}`,
      {
        method: request.method,
        body,
        cache: "no-store",
        signal: AbortSignal.timeout(request.method === "GET" ? 15000 : 240000),
        headers: {
          "Content-Type": "application/json",
          ...(request.method !== "GET"
            ? { Authorization: `Bearer ${process.env.AEGIS_CONTROL_TOKEN}` }
            : {}),
        },
      },
    );
    return new NextResponse(await upstream.text(), {
      status: upstream.status,
      headers: {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      },
    });
  } catch {
    return NextResponse.json(
      { detail: "Control API unavailable. Check the local service and retry." },
      { status: 503 },
    );
  }
}
export { proxy as GET, proxy as POST };
