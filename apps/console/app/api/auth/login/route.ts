import { NextRequest, NextResponse } from "next/server";
import {
  COOKIE,
  demoUsername,
  demoPassword,
  issueSession,
} from "../../../session";
export async function POST(request: NextRequest) {
  const origin = request.headers.get("origin");
  if (!origin || new URL(origin).host !== request.headers.get("host"))
    return NextResponse.json({ detail: "Invalid origin" }, { status: 403 });
  try {
    const body = await request.text();
    if (body.length > 4096)
      return NextResponse.json(
        { detail: "Request too large" },
        { status: 413 },
      );
    const { username, password } = JSON.parse(body);
    if (username !== demoUsername || password !== demoPassword)
      return NextResponse.json(
        { detail: "The username or password is incorrect." },
        { status: 401 },
      );
    const response = NextResponse.json({ ok: true });
    response.cookies.set(COOKIE, issueSession(), {
      httpOnly: true,
      sameSite: "strict",
      secure: request.nextUrl.protocol === "https:",
      path: "/",
      maxAge: 8 * 60 * 60,
    });
    return response;
  } catch {
    return NextResponse.json(
      {
        detail:
          "Login is unavailable. Start the local control service and try again.",
      },
      { status: 503 },
    );
  }
}
