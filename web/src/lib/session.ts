import { createHmac, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE = "ga_session";
export const SESSION_TTL_SECONDS = 60 * 60 * 24 * 30;

function secret(): string | null {
  const value = process.env.SESSION_SECRET;
  return value && value.length >= 32 ? value : null;
}

function sign(payload: string, key: string): string {
  return createHmac("sha256", key).update(payload).digest("base64url");
}

export function createSessionToken(now = Date.now()): string {
  const key = secret();
  if (!key) throw new Error("SESSION_SECRET must be set to at least 32 characters");
  const payload = `owner.${Math.floor(now / 1000) + SESSION_TTL_SECONDS}`;
  return `${payload}.${sign(payload, key)}`;
}

export function verifySessionToken(token: string | undefined, now = Date.now()): boolean {
  const key = secret();
  if (!key || !token) return false;
  const lastDot = token.lastIndexOf(".");
  if (lastDot < 0) return false;
  const payload = token.slice(0, lastDot);
  const given = Buffer.from(token.slice(lastDot + 1));
  const expected = Buffer.from(sign(payload, key));
  if (given.length !== expected.length || !timingSafeEqual(given, expected)) return false;
  const expires = Number(payload.split(".")[1]);
  return Number.isFinite(expires) && expires * 1000 > now;
}

export function passwordMatches(candidate: string): boolean {
  const expected = process.env.OWNER_PASSWORD;
  if (!expected || expected.length < 8) return false;
  const key = secret() ?? "unset";
  // Compare fixed-length digests so the comparison time does not depend on length.
  const a = createHmac("sha256", key).update(candidate).digest();
  const b = createHmac("sha256", key).update(expected).digest();
  return timingSafeEqual(a, b);
}

export function authConfigured(): boolean {
  return Boolean(secret() && process.env.OWNER_PASSWORD && process.env.OWNER_PASSWORD.length >= 8);
}

export function cookieSecure(): boolean {
  return process.env.COOKIE_SECURE === "true";
}
