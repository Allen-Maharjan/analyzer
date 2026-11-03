import { NextResponse, type NextRequest } from "next/server";

import { SESSION_COOKIE, verifySessionToken } from "@/lib/session";

const PUBLIC_PATHS = ["/login", "/api/login"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.includes(pathname);

  // State-changing requests must come from this site (CSRF defence alongside SameSite=Strict).
  if (request.method !== "GET" && request.method !== "HEAD") {
    const origin = request.headers.get("origin");
    const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
    if (!origin || !host || new URL(origin).host !== host) {
      return NextResponse.json({ message: "Request blocked: it did not come from this app." }, { status: 403 });
    }
  }

  if (isPublic) return NextResponse.next();
  if (verifySessionToken(request.cookies.get(SESSION_COOKIE)?.value)) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ message: "Please sign in again." }, { status: 401 });
  }
  const login = pathname === "/" ? "/login" : `/login?next=${encodeURIComponent(pathname)}`;
  // Build from the Host header: inside Docker, request.url names the container address.
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host") ?? request.nextUrl.host;
  const proto = request.headers.get("x-forwarded-proto") ?? request.nextUrl.protocol.replace(":", "");
  return NextResponse.redirect(`${proto}://${host}${login}`);
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico|icon.svg).*)"],
};
