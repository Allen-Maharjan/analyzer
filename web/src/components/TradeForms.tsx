"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { nepalTime, rupees } from "@/lib/format";

type Trade = { id: number; side: "buy" | "sell"; quantity_tola: number; price_npr: number; traded_at: string; note: string };
type Draft = { side: "buy" | "sell"; quantity: string; price: string; when: string; note: string };

const input = "num min-h-11 rounded-xl border border-line bg-panel px-3 text-base";
const primary = "min-h-11 rounded-xl bg-accent px-4 text-sm font-semibold text-on-accent hover:bg-accent-hover disabled:opacity-50";
const secondary = "min-h-11 rounded-xl border border-line px-4 text-sm font-medium hover:bg-hover";

/** Local date-time for <input type="datetime-local">, in the browser's own time zone. */
function localInput(iso?: string): string {
  const d = iso ? new Date(iso) : new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function blank(price?: number | null): Draft {
  return { side: "buy", quantity: "", price: price ? String(price) : "", when: localInput(), note: "" };
}

/** The owner's own record of what they bought and sold. Nothing here places an order. */
export function TradeLog({ asset, trades, nepalPrice }: { asset: string; trades: Trade[]; nepalPrice: number | null }) {
  const router = useRouter();
  const [draft, setDraft] = useState<Draft>(() => blank(nepalPrice));
  const [editing, setEditing] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(path: string, method: string, body?: unknown) {
    setBusy(true);
    setError(null);
    const response = await fetch(`${path}?asset=${encodeURIComponent(asset)}`, {
      method,
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    setBusy(false);
    if (!response?.ok) {
      setError("Couldn't save that. Check the numbers and try again.");
      return false;
    }
    router.refresh();
    return true;
  }

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const quantity = Number(draft.quantity.replace(/,/g, ""));
    const price = Number(draft.price.replace(/[Rs,\s]/g, ""));
    const when = new Date(draft.when);
    if (!(quantity > 0) || !(price > 0) || Number.isNaN(when.getTime())) {
      setError("Enter the tola, the price per tola and the date.");
      return;
    }
    const body = { side: draft.side, quantity_tola: quantity, price_npr: price, traded_at: when.toISOString(), note: draft.note };
    const ok = editing == null ? await send("/api/trade/trades", "POST", body) : await send(`/api/trade/trades/${editing}`, "PUT", body);
    if (ok) {
      setEditing(null);
      setDraft(blank(nepalPrice));
    }
  }

  function edit(t: Trade) {
    setEditing(t.id);
    setDraft({ side: t.side, quantity: String(t.quantity_tola), price: String(t.price_npr), when: localInput(t.traded_at), note: t.note });
  }

  return (
    <div>
      {trades.length === 0 ? (
        <p className="text-ink-2">No trades recorded yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {trades.map((t) => (
            <li key={t.id} className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2">
              <span className="num text-[15px]">
                <span className={`font-semibold ${t.side === "buy" ? "text-buy" : "text-wait"}`}>{t.side === "buy" ? "Bought" : "Sold"}</span>{" "}
                {t.quantity_tola} tola at {rupees(t.price_npr)}
                <span className="block text-xs text-ink-2">
                  {nepalTime(t.traded_at)}
                  {t.note ? ` · ${t.note}` : ""}
                </span>
              </span>
              <span className="flex gap-1">
                <button type="button" className="min-h-11 rounded-xl px-3 text-sm text-ink-2 hover:bg-hover hover:text-ink" onClick={() => edit(t)}>
                  Correct
                </button>
                <button
                  type="button"
                  disabled={busy}
                  className="min-h-11 rounded-xl px-3 text-sm text-ink-2 hover:bg-hover hover:text-wait"
                  onClick={() => window.confirm("Delete this trade from your record?") && send(`/api/trade/trades/${t.id}`, "DELETE")}
                >
                  Delete
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={save} className="mt-4 rounded-xl border border-line bg-inset p-4">
        <p className="mb-3 text-sm font-medium">{editing == null ? "Record a trade you made" : "Correct this trade"}</p>
        <div role="group" aria-label="Bought or sold" className="mb-3 inline-flex rounded-xl border border-line bg-panel p-1">
          {(["buy", "sell"] as const).map((side) => (
            <button
              key={side}
              type="button"
              aria-pressed={draft.side === side}
              onClick={() => setDraft({ ...draft, side })}
              className={`min-h-9 min-w-20 rounded-lg px-4 text-[15px] ${draft.side === side ? "bg-accent-soft font-semibold text-accent-hover" : "text-ink-2"}`}
            >
              {side === "buy" ? "Bought" : "Sold"}
            </button>
          ))}
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="grid gap-1 text-sm">
            <span>Tola</span>
            <input inputMode="decimal" className={input} value={draft.quantity} onChange={(e) => setDraft({ ...draft, quantity: e.target.value })} />
          </label>
          <label className="grid gap-1 text-sm">
            <span>Price per tola (Rs)</span>
            <input inputMode="decimal" className={input} value={draft.price} onChange={(e) => setDraft({ ...draft, price: e.target.value })} />
          </label>
          <label className="grid gap-1 text-sm">
            <span>When</span>
            <input type="datetime-local" className={input} value={draft.when} onChange={(e) => setDraft({ ...draft, when: e.target.value })} />
          </label>
          <label className="grid gap-1 text-sm">
            <span>Note (optional)</span>
            <input className={input} maxLength={300} value={draft.note} onChange={(e) => setDraft({ ...draft, note: e.target.value })} />
          </label>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="submit" disabled={busy} className={primary}>
            {editing == null ? "Save trade" : "Save correction"}
          </button>
          {editing != null && (
            <button type="button" className={secondary} onClick={() => { setEditing(null); setDraft(blank(nepalPrice)); }}>
              Cancel
            </button>
          )}
        </div>
        {error && <p role="status" className="mt-2 text-sm text-wait">{error}</p>}
      </form>
    </div>
  );
}

/** Budget and the shop's buy-back gap. The gap has no default: profit figures wait for it. */
export function TradeSettingsForm({ asset, budget, gapPct }: { asset: string; budget: number; gapPct: number | null }) {
  const router = useRouter();
  const [b, setB] = useState(String(budget));
  const [g, setG] = useState(gapPct == null ? "" : String(gapPct));
  const [message, setMessage] = useState<{ tone: "ok" | "error"; text: string } | null>(null);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    const budgetValue = Number(b.replace(/[Rs,\s]/g, ""));
    const gapValue = g.trim() === "" ? null : Number(g.replace("%", ""));
    if (!(budgetValue >= 1000) || (gapValue != null && !(gapValue >= 0 && gapValue <= 20))) {
      setMessage({ tone: "error", text: "Budget from Rs 1,000; gap from 0 to 20%." });
      return;
    }
    const response = await fetch(`/api/trade/settings?asset=${encodeURIComponent(asset)}`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ budget: budgetValue, gap_pct: gapValue }),
    }).catch(() => null);
    if (!response?.ok) {
      setMessage({ tone: "error", text: "Couldn't save. Try again." });
      return;
    }
    setMessage({ tone: "ok", text: "Saved." });
    router.refresh();
  }

  return (
    <form onSubmit={save} className="grid gap-3 sm:grid-cols-2">
      <label className="grid gap-1 text-sm">
        <span>Budget (Rs)</span>
        <input inputMode="numeric" className={input} value={b} onChange={(e) => setB(e.target.value)} />
      </label>
      <label className="grid gap-1 text-sm">
        <span>Shop&apos;s buy-back gap (%)</span>
        <input inputMode="decimal" placeholder="Ask your shop" className={input} value={g} onChange={(e) => setG(e.target.value)} />
        <span className="text-xs text-ink-2">How much less than the day&apos;s price the shop pays when you sell back.</span>
      </label>
      <div className="sm:col-span-2">
        <button type="submit" className={primary}>Save</button>
        {message && <span role="status" className={`ml-3 text-sm ${message.tone === "error" ? "text-wait" : "text-buy"}`}>{message.text}</span>}
      </div>
    </form>
  );
}
