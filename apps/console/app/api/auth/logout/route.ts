import { NextRequest, NextResponse } from "next/server";
import { COOKIE } from "../../../session";
export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (!origin || new URL(origin).host !== request.headers.get("host"))
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  const response = NextResponse.json({ ok: true });
  response.cookies.set(COOKIE, "", { path: "/", maxAge: 0 });
  return response;
}
