"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type Plan = { waiting_since: string | null; completed_at: string | null };

/** The waiting clock only changes when the owner says so. */
export function PlanActions({ plan, asset, label }: { plan: Plan; asset: string; label: string }) {
  const router = useRouter();
  const [confirming, setConfirming] = useState<null | "purchased" | "restart">(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(action: "purchased" | "restart") {
    setBusy(true);
    setError(null);
    const response = await fetch(`/api/plan/${action}?asset=${encodeURIComponent(asset)}`, { method: "POST" }).catch(() => null);
    setBusy(false);
    if (!response?.ok) {
      setError("Couldn't save that. Check your connection and try again.");
      return;
    }
    setConfirming(null);
    router.refresh();
  }

  if (confirming) {
    const text =
      confirming === "purchased"
        ? "Mark the purchase as done? The app will stop counting waiting days."
        : "Start a new purchase plan? The waiting count goes back to zero.";
    return (
      <div className="rounded-md border border-line p-4">
        <p className="text-sm">{text}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => send(confirming)}
            className="min-h-11 rounded-md bg-accent px-4 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-60"
          >
            {confirming === "purchased" ? "Yes, I bought it" : "Yes, start over"}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(null)}
            className="min-h-11 rounded-md border border-line px-4 text-sm font-medium hover:bg-hover"
          >
            Cancel
          </button>
        </div>
        {error && <p className="mt-2 text-sm text-wait">{error}</p>}
      </div>
    );
  }

  return (
    <div className="flex flex-wrap gap-2">
      {!plan.completed_at && (
        <button
          type="button"
          onClick={() => setConfirming("purchased")}
          className="min-h-11 rounded-md border border-line px-4 text-sm font-medium hover:bg-hover"
        >
          I bought {label}
        </button>
      )}
      <button
        type="button"
        onClick={() => setConfirming("restart")}
        className="min-h-11 rounded-md px-4 text-sm font-medium text-ink-2 hover:bg-hover hover:text-ink"
      >
        Start a new plan
      </button>
    </div>
  );
}
