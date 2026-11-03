"use client";

import { X } from "lucide-react";
import { useState } from "react";

export function WatchLevelsForm({ initial, asset }: { initial: number[]; asset: string }) {
  const [levels, setLevels] = useState(initial);
  const [draft, setDraft] = useState("");
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function save(next: number[]) {
    setBusy(true);
    setMessage(null);
    const response = await fetch(`/api/settings/watch-levels?asset=${encodeURIComponent(asset)}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ levels: next }),
    }).catch(() => null);
    setBusy(false);
    if (!response?.ok) {
      setMessage({ tone: "error", text: "Couldn't save. Check the number and try again." });
      return;
    }
    const body = await response.json();
    setLevels(body.levels);
    setDraft("");
    setMessage({ tone: "ok", text: "Saved. The next analysis will use it." });
  }

  function add(event: React.FormEvent) {
    event.preventDefault();
    const value = Number(draft.replace(/[$,\s]/g, ""));
    if (!Number.isFinite(value) || value <= 0 || value >= 100000) {
      setMessage({ tone: "error", text: "Enter a positive world price in US dollars." });
      return;
    }
    save([...levels, value]);
  }

  return (
    <div>
      <ul className="flex flex-wrap gap-2">
        {levels.length === 0 && <li className="text-sm text-ink-2">No watch levels.</li>}
        {levels.map((level) => (
          <li key={level} className="num inline-flex items-center gap-1 rounded-full border border-line bg-panel py-1 pl-3 pr-1 text-sm">
            ${level.toLocaleString("en-US")}
            <button
              type="button"
              disabled={busy}
              onClick={() => save(levels.filter((l) => l !== level))}
              aria-label={`Remove $${level}`}
              className="grid size-10 place-items-center rounded-full text-ink-2 hover:bg-hover hover:text-ink"
            >
              <X aria-hidden className="size-4" />
            </button>
          </li>
        ))}
      </ul>
      <form onSubmit={add} className="mt-3 flex flex-wrap items-end gap-2">
        <label className="grid gap-1 text-sm">
          <span className="font-medium">Add a level (US$ per ounce)</span>
          <input
            inputMode="decimal"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder="Price"
            className="num min-h-11 w-40 rounded-xl border border-line bg-panel px-3 text-base placeholder:text-ink-2/70"
          />
        </label>
        <button
          type="submit"
          disabled={busy || !draft}
          className="min-h-11 rounded-xl bg-accent px-4 text-sm font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
        >
          Add
        </button>
      </form>
      {message && (
        <p role="status" className={`mt-2 text-sm ${message.tone === "error" ? "text-wait" : "text-buy"}`}>
          {message.text}
        </p>
      )}
    </div>
  );
}
