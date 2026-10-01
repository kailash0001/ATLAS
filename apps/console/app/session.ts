import { createHmac, timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
export const COOKIE = "atlas_session";
export const demoUsername = "atlas";
export const demoPassword = "atlas_local";
function key() {
  return (
    process.env.ATLAS_SESSION_SECRET || process.env.AEGIS_CONTROL_TOKEN || ""
  );
}
export function issueSession() {
  if (!key())
    throw new Error("Configure the local operator service before signing in");
  const payload = Buffer.from(
    JSON.stringify({
      user: demoUsername,
      expires: Date.now() + 8 * 60 * 60 * 1000,
    }),
  ).toString("base64url");
  return `${payload}.${createHmac("sha256", key()).update(payload).digest("base64url")}`;
}
export function validSession(value: string | undefined) {
  if (!value || !key()) return false;
  try {
    const [payload, signature, ...extra] = value.split(".");
    if (extra.length) return false;
    const expected = createHmac("sha256", key()).update(payload).digest();
    const actual = Buffer.from(signature, "base64url");
    if (actual.length !== expected.length || !timingSafeEqual(actual, expected))
      return false;
    const data = JSON.parse(Buffer.from(payload, "base64url").toString());
    return (
      data.user === demoUsername &&
      Number.isFinite(data.expires) &&
      data.expires > Date.now()
    );
  } catch {
    return false;
  }
}
export async function signedIn() {
  return validSession((await cookies()).get(COOKIE)?.value);
}
