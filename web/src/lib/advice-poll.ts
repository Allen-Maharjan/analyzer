/** Client helpers to wait for a cloud update (2–4 minutes) to produce newer advice. */

export const POLL_EVERY_MS = 20_000;
export const POLL_FOR_MS = 6 * 60_000;

export async function adviceCreatedAt(asset: string): Promise<string | null> {
  const response = await fetch(`/api/dashboard?asset=${encodeURIComponent(asset)}`, { cache: "no-store" }).catch(() => null);
  if (!response?.ok) return null;
  const body = (await response.json().catch(() => ({}))) as { created_at?: string };
  return body.created_at ?? null;
}

/** True once the advice's created_at differs from `since`; false after `timeoutMs` or on abort. */
export async function waitForNewAdvice(asset: string, since: string | null, signal?: AbortSignal, timeoutMs = POLL_FOR_MS): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, POLL_EVERY_MS));
    if (signal?.aborted) return false;
    const latest = await adviceCreatedAt(asset);
    if (latest && latest !== since) return true;
  }
  return false;
}
