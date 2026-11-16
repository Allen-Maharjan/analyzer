"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import { waitForNewAdvice } from "@/lib/advice-poll";
import { ageWords } from "@/lib/format";

// Above this age, while the world market is open, the page says how old the advice is.
const OLD_ADVICE_SECONDS = 45 * 60;

type State = "checking" | "idle" | "updating" | "timeout";

/**
 * On page open, asks the API to start an update if the advice is over 20 minutes old. While one runs,
 * checks every 20 s for newer advice (up to 6 minutes) and then reloads the page.
 */
export function AutoRefresh({
  asset,
  createdAt,
  ageSeconds,
  marketOpen,
  reloadHref,
}: {
  asset: string;
  createdAt: string;
  ageSeconds: number;
  marketOpen: boolean;
  /** Where to go once newer advice exists; defaults to reloading this page. */
  reloadHref?: string;
}) {
  const router = useRouter();
  const [state, setState] = useState<State>("checking");
  const [, startTransition] = useTransition();

  useEffect(() => {
    const abort = new AbortController();
    (async () => {
      const response = await fetch("/api/refresh/auto", { method: "POST" }).catch(() => null);
      const body = response?.ok ? ((await response.json().catch(() => ({}))) as { updating?: boolean }) : {};
      if (abort.signal.aborted) return;
      if (!body.updating) {
        setState("idle");
        return;
      }
      setState("updating");
      const changed = await waitForNewAdvice(asset, createdAt, abort.signal);
      if (abort.signal.aborted) return;
      if (changed) {
        setState("idle");
        startTransition(() => (reloadHref ? router.replace(reloadHref) : router.refresh()));
      } else {
        setState("timeout");
      }
    })();
    return () => abort.abort();
  }, [asset, createdAt, reloadHref, router]);

  const old = marketOpen && ageSeconds > OLD_ADVICE_SECONDS;
  if (!old && state !== "updating" && state !== "timeout") return null;

  const line =
    state === "updating"
      ? "Getting the latest prices, about 3 minutes."
      : state === "timeout"
        ? "The update is still running. Check again in a few minutes."
        : "";
  return (
    <p
      role="status"
      className={`mb-4 flex items-start gap-2 rounded-2xl border p-4 text-[15px] ${old ? "border-watch/20 bg-watch-soft text-ink" : "border-line bg-panel text-ink-2"}`}
    >
      {state === "updating" && <RefreshCw aria-hidden className="mt-0.5 size-4 shrink-0 animate-spin" strokeWidth={1.75} />}
      <span>
        {old && <span className="font-semibold">This advice is {ageWords(ageSeconds)} old. </span>}
        {state === "updating" && old ? "Getting a newer one, about 3 minutes." : line}
      </span>
    </p>
  );
}
