"use client";

import { useState } from "react";

import { PROVIDER_NAMES, type AiOverview } from "@/lib/ai";

export function AiSettingsForm({ settings, runner }: { settings: AiOverview["settings"]; runner: AiOverview["runner"] }) {
  const [provider, setProvider] = useState(settings.provider);
  const [model, setModel] = useState(settings.model ?? "");
  const [automatic, setAutomatic] = useState(settings.automatic);
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    const response = await fetch("/api/settings/ai", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ provider, model: model.trim() || null, automatic }),
    }).catch(() => null);
    setBusy(false);
    setMessage(response?.ok ? { tone: "ok", text: "Saved." } : { tone: "error", text: "Couldn't save. Check the model name." });
  }

  const seenMinutes = runner ? Math.round((Date.now() - Date.parse(runner.seen_at)) / 60000) : null;
  return (
    <form onSubmit={save} className="grid gap-4">
      <fieldset className="grid gap-2">
        <legend className="mb-1 text-sm font-medium">Which AI</legend>
        {(["codex", "claude", "kiro", "openrouter"] as const).map((p) => {
          const status = runner?.providers[p];
          return (
            <label key={p} className="flex min-h-11 cursor-pointer items-center gap-3 rounded-xl border border-line px-3 has-[:checked]:border-accent has-[:checked]:bg-accent-soft/40">
              <input type="radio" name="provider" value={p} checked={provider === p} onChange={() => setProvider(p)} className="accent-[var(--color-accent)]" />
              <span className="flex-1 font-medium">{PROVIDER_NAMES[p]}</span>
              <span className={`text-xs ${status?.ready ? "text-buy" : "text-ink-2"}`}>
                {status ? (status.ready ? "ready" : status.error ?? "not ready") : "unknown"}
              </span>
            </label>
          );
        })}
      </fieldset>
      {provider !== "openrouter" && <label className="grid gap-1 text-sm">
        <span className="font-medium">Model (optional)</span>
        <input
          value={model}
          onChange={(e) => setModel(e.target.value)}
          placeholder="Leave empty for the default"
          className="min-h-11 rounded-xl border border-line bg-panel px-3 text-base placeholder:text-ink-2/70"
        />
      </label>}
      {provider === "openrouter" && <p className="text-sm text-ink-2">Free compatible models are discovered automatically. Set GA_OPENROUTER_API_KEY in the host runner environment.</p>}
      <label className="flex min-h-11 items-center gap-3 text-[15px]">
        <input type="checkbox" checked={automatic} onChange={(e) => setAutomatic(e.target.checked)} className="size-4 accent-[var(--color-accent)]" />
        Run automatically every 4 hours and when the advice changes (at most 12 times a day)
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button type="submit" disabled={busy} className="min-h-11 rounded-xl bg-accent px-4 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-60">
          Save
        </button>
        {message && <span role="status" className={`text-sm ${message.tone === "error" ? "text-wait" : "text-buy"}`}>{message.text}</span>}
      </div>
      <p className="text-xs text-ink-2">
        {runner
          ? seenMinutes != null && seenMinutes > 3
            ? `The AI runner on this computer was last seen ${seenMinutes} min ago. Start it with: systemctl --user start gold-ai-runner`
            : "The AI runner on this computer is connected."
          : "The AI runner hasn't connected yet. See the README to start it."}
      </p>
    </form>
  );
}
