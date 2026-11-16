"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { adviceCreatedAt, waitForNewAdvice } from "@/lib/advice-poll";

type State = { kind: "idle" } | { kind: "busy"; message?: string } | { kind: "done" | "error"; message: string };

/**
 * Re-checks the once-a-day sources (Nepal price and the dollar rate) and starts a full update, then
 * waits until newer advice exists before saying so. A cloud update takes 2–4 minutes.
 */
export function RefreshButton({ asset = "gold" }: { asset?: string }) {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "idle" });
  const [, startTransition] = useTransition();
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  function finish(next: State) {
    setState(next);
    setTimeout(() => setState({ kind: "idle" }), 8000);
  }

  async function refresh() {
    setState({ kind: "busy" });
    try {
      const since = await adviceCreatedAt(asset);
      const responses = await Promise.all(
        ["nepal_rates", "usd_npr"].map((target) => fetch(`/api/refresh/${target}`, { method: "POST" })),
      );
      if (responses.some((r) => r.status === 401)) {
        window.location.assign("/login");
        return;
      }
      const failed = responses.find((r) => !r.ok && r.status !== 429);
      if (failed) {
        const body = await failed.json().catch(() => ({}));
        setState({ kind: "error", message: body.message ?? "Couldn't reach the price sources. Try again shortly." });
        return;
      }
      if (responses.every((r) => r.status === 429)) {
        finish({ kind: "done", message: "An update was started in the last minute. Its advice appears here when it's ready." });
        return;
      }
      setState({ kind: "busy", message: "Getting the latest prices, about 3 minutes." });
      abort.current = new AbortController();
      const changed = await waitForNewAdvice(asset, since, abort.current.signal);
      if (abort.current.signal.aborted) return;
      if (changed) {
        startTransition(() => router.refresh());
        finish({ kind: "done", message: "Showing the latest advice." });
      } else {
        finish({ kind: "done", message: "The update is still running. Check again in a few minutes." });
      }
    } catch {
      setState({ kind: "error", message: "No connection. Check your internet and try again." });
    }
  }

  const busy = state.kind === "busy";
  const message = state.kind === "idle" ? null : state.message;
  return (
    <div className="relative">
      <button
        type="button"
        onClick={refresh}
        disabled={busy}
        className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 px-1 text-[15px] text-ink-2 transition-colors hover:text-ink disabled:cursor-wait"
      >
        <RefreshCw aria-hidden className={`size-4 ${busy ? "animate-spin" : ""}`} strokeWidth={1.75} />
        <span className="sr-only sm:not-sr-only">{busy ? "Updating…" : "Refresh"}</span>
      </button>
      {message && (
        <p
          role="status"
          className={`absolute right-0 top-full mt-1 w-max max-w-[15rem] rounded-xl border border-line bg-panel px-3 py-2 text-sm shadow-[0_4px_12px_rgb(0_0_0_/_0.25)] ${
            state.kind === "error" ? "text-wait" : "text-ink"
          }`}
        >
          {message}
        </p>
      )}
    </div>
  );
}
