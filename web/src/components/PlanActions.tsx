"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

type Plan = { waiting_since: string | null; completed_at: string | null; first_part_at?: string | null };
type Action = "purchased" | "restart" | "first_part";

const CONFIRM: Record<Action, { text: string; yes: string }> = {
  purchased: { text: "Mark the purchase as done? The app will stop counting waiting days.", yes: "Yes, I bought it" },
  first_part: {
    text: "Record that you bought the first half? The app keeps today's triggers for the second half until you buy it.",
    yes: "Yes, I bought the first half",
  },
  restart: { text: "Start a new purchase plan? The waiting count goes back to zero.", yes: "Yes, start over" },
};

/** The waiting clock only changes when the owner says so. */
export function PlanActions({
  plan,
  asset,
  label,
  twoPart = null,
}: {
  plan: Plan;
  asset: string;
  label: string;
  /** "first": the advice is to buy half now; "second": the first half is recorded. */
  twoPart?: "first" | "second" | null;
}) {
  const router = useRouter();
  const [confirming, setConfirming] = useState<Action | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(action: Action) {
    setBusy(true);
    setError(null);
    const response = await fetch(`/api/plan/${action}?asset=${encodeURIComponent(asset)}`, { method: "POST" }).catch(() => null);
    setBusy(false);
    if (!response?.ok) {
      const body = response ? await response.json().catch(() => ({})) : {};
      setError(body.detail ?? body.message ?? "Couldn't save that. Check your connection and try again.");
      return;
    }
    setConfirming(null);
    router.refresh();
  }

  if (confirming) {
    return (
      <div className="rounded-xl border border-line bg-inset p-4">
        <p className="text-sm">{CONFIRM[confirming].text}</p>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => send(confirming)}
            className="min-h-11 rounded-xl bg-accent px-4 text-sm font-semibold text-on-accent hover:bg-accent-hover disabled:opacity-60"
          >
            {CONFIRM[confirming].yes}
          </button>
          <button
            type="button"
            onClick={() => setConfirming(null)}
            className="min-h-11 rounded-xl border border-line px-4 text-sm font-medium hover:bg-hover"
          >
            Cancel
          </button>
        </div>
        {error && <p className="mt-2 text-sm text-wait">{error}</p>}
      </div>
    );
  }

  const button = "min-h-11 rounded-xl border border-line px-4 text-sm font-medium hover:bg-hover";
  return (
    <div className="flex flex-wrap gap-2">
      {!plan.completed_at && twoPart === "first" && (
        <button type="button" onClick={() => setConfirming("first_part")} className={button}>
          I bought the first half
        </button>
      )}
      {!plan.completed_at && (
        <button type="button" onClick={() => setConfirming("purchased")} className={button}>
          {twoPart === "second" ? "I bought the second half" : twoPart === "first" ? `I bought all the ${label}` : `I bought ${label}`}
        </button>
      )}
      <button
        type="button"
        onClick={() => setConfirming("restart")}
        className="min-h-11 rounded-xl px-4 text-sm font-medium text-ink-2 hover:bg-hover hover:text-ink"
      >
        Start a new plan
      </button>
    </div>
  );
}
