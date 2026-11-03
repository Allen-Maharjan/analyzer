import { cookies } from "next/headers";

import { seeOther } from "@/lib/redirect";
import { SESSION_COOKIE, SESSION_TTL_SECONDS, authConfigured, cookieSecure, createSessionToken, passwordMatches } from "@/lib/session";

const FAILURE_DELAY_MS = 800;

export async function POST(request: Request) {
  const form = await request.formData();
  const password = String(form.get("password") ?? "");
  const nextRaw = String(form.get("next") ?? "/");
  const next = nextRaw.startsWith("/") && !nextRaw.startsWith("//") ? nextRaw : "/";

  if (!authConfigured()) return seeOther("/login?error=setup");
  if (!passwordMatches(password)) {
    await new Promise((resolve) => setTimeout(resolve, FAILURE_DELAY_MS));
    return seeOther(`/login?error=wrong&next=${encodeURIComponent(next)}`);
  }
  (await cookies()).set(SESSION_COOKIE, createSessionToken(), {
    httpOnly: true,
    sameSite: "strict",
    secure: cookieSecure(),
    path: "/",
    maxAge: SESSION_TTL_SECONDS,
  });
  return seeOther(next);
}
