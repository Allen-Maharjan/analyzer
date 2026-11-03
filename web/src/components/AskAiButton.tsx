"use client";

import { Sparkles } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

export function AskAiButton({ busy: initiallyBusy = false, asset }: { busy?: boolean; asset: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState(initiallyBusy);
  const [message, setMessage] = useState<string | null>(null);

  async function ask() {
    setBusy(true);
    setMessage(null);
    const response = await fetch(`/api/ai/request?asset=${encodeURIComponent(asset)}`, { method: "POST" }).catch(() => null);
    const body = await response?.json().catch(() => ({}));
    if (!response || (!response.ok && response.status !== 409)) {
      setBusy(false);
      setMessage(body?.message ?? "Couldn't ask the AI. Try again shortly.");
      return;
    }
    setMessage(body?.message ?? "Asked the AI.");
    // Poll for the answer: the runner takes 30–90 seconds.
    for (let i = 0; i < 12; i++) {
      await new Promise((r) => setTimeout(r, 10000));
      const status = await fetch(`/api/ai/status?asset=${encodeURIComponent(asset)}`).then((r) => r.json()).catch(() => null);
      if (status && !["queued", "running"].includes(status.status)) break;
    }
    setBusy(false);
    setMessage(null);
    router.refresh();
  }

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        type="button"
        onClick={ask}
        disabled={busy}
        className="inline-flex min-h-11 items-center gap-1.5 rounded-xl border border-line bg-panel px-4 text-[15px] font-medium transition-colors hover:bg-hover disabled:cursor-wait disabled:opacity-60"
      >
        <Sparkles aria-hidden className={`size-4 text-accent ${busy ? "animate-pulse" : ""}`} strokeWidth={1.75} />
        {busy ? "AI is thinking…" : "Ask AI again"}
      </button>
      {message && (
        <span role="status" className="text-sm text-ink-2">
          {message}
        </span>
      )}
    </div>
  );
}
