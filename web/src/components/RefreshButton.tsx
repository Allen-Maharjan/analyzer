"use client";

import { RefreshCw } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

type State = { kind: "idle" } | { kind: "busy" } | { kind: "done" | "error"; message: string };

/** Re-checks the once-a-day sources (Nepal gold and the dollar rate), then reloads the advice. */
export function RefreshButton() {
  const router = useRouter();
  const [state, setState] = useState<State>({ kind: "idle" });
  const [, startTransition] = useTransition();

  async function refresh() {
    setState({ kind: "busy" });
    try {
      const responses = await Promise.all(
        ["nepal_rates", "usd_npr"].map((target) => fetch(`/api/refresh/${target}`, { method: "POST" })),
      );
      if (responses.some((r) => r.status === 401)) {
        window.location.assign("/login");
        return;
      }
      const limited = responses.every((r) => r.status === 429);
      const failed = responses.find((r) => !r.ok && r.status !== 429);
      if (failed) {
        const body = await failed.json().catch(() => ({}));
        setState({ kind: "error", message: body.message ?? "Couldn't reach the price sources. Try again shortly." });
        return;
      }
      // Collection and analysis take a few seconds; reload the advice after they finish.
      await new Promise((resolve) => setTimeout(resolve, limited ? 0 : 8000));
      startTransition(() => router.refresh());
      setState({ kind: "done", message: limited ? "Already checked in the last minute." : "Checked. Showing the latest advice." });
      setTimeout(() => setState({ kind: "idle" }), 6000);
    } catch {
      setState({ kind: "error", message: "No connection. Check your internet and try again." });
    }
  }

  const busy = state.kind === "busy";
  return (
    <div className="relative">
      <button
        type="button"
        onClick={refresh}
        disabled={busy}
        className="inline-flex min-h-11 items-center gap-1.5 px-1 text-[15px] text-ink-2 transition-colors hover:text-ink disabled:cursor-wait"
      >
        <RefreshCw aria-hidden className={`size-4 ${busy ? "animate-spin" : ""}`} strokeWidth={1.75} />
        {busy ? "Checking…" : "Refresh"}
      </button>
      {state.kind !== "idle" && state.kind !== "busy" && (
        <p
          role="status"
          className={`absolute right-0 top-full mt-1 w-max max-w-[15rem] rounded-xl border border-line bg-panel px-3 py-2 text-sm shadow-[0_4px_12px_rgb(28_25_23_/_0.10)] ${
            state.kind === "error" ? "text-wait" : "text-ink"
          }`}
        >
          {state.message}
        </p>
      )}
    </div>
  );
}
