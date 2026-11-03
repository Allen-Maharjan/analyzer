"use client";

import { useEffect, useState } from "react";

import { CandleChart } from "@/components/CandleChart";
import { nepalTime, usd } from "@/lib/format";

type Candle = { bucket_start: string; open: number; high: number; low: number; close: number };
type Level = { id: string; price: number; kind: string; manual: boolean };
type Quote = { price: string | number; source: string; observed_at: string; freshness: { status: string } };
type Timeframe = "15m" | "1h" | "1D";
const OPTIONS: { value: Timeframe; label: string }[] = [
  { value: "15m", label: "15 minutes" },
  { value: "1h", label: "1 hour" },
  { value: "1D", label: "1 day" },
];
const SOURCE_NAMES: Record<string, string> = { gold_api: "Gold API", swissquote: "Swissquote" };

export function WorldChart({ asset, label, initialCandles, levels }: {
  asset: string; label: string; initialCandles: Candle[]; levels: Level[];
}) {
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [series, setSeries] = useState<{ timeframe: Timeframe; candles: Candle[] }>({ timeframe: "15m", candles: initialCandles });
  const candles = series.timeframe === timeframe ? series.candles : [];
  const [quote, setQuote] = useState<Quote | null>(null);
  const [candleError, setCandleError] = useState(false);
  const [quoteError, setQuoteError] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let active = true;
    let fetching = false;
    let controller: AbortController | null = null;
    setCandleError(false);
    setLoading(true);

    async function update() {
      if (fetching || document.visibilityState === "hidden") return;
      fetching = true;
      controller = new AbortController();
      const timeout = window.setTimeout(() => controller?.abort(), 20_000);
      const query = new URLSearchParams({ asset, timeframe });
      const quoteQuery = new URLSearchParams({ asset });
      const [bars, spot] = await Promise.allSettled([
        fetch(`/api/market/candles?${query}`, { cache: "no-store", signal: controller.signal }).then(async (r) => {
          if (!r.ok) throw new Error("candles unavailable");
          return r.json() as Promise<{ candles: Candle[] }>;
        }),
        fetch(`/api/market/quote?${quoteQuery}`, { cache: "no-store", signal: controller.signal }).then(async (r) => {
          if (!r.ok) throw new Error("quote unavailable");
          return r.json() as Promise<Quote>;
        }),
      ]);
      window.clearTimeout(timeout);
      fetching = false;
      if (!active) return;
      setLoading(false);
      if (bars.status === "fulfilled") {
        setSeries({ timeframe, candles: bars.value.candles });
        setCandleError(false);
      } else setCandleError(true);
      if (spot.status === "fulfilled") {
        setQuote(spot.value);
        setQuoteError(false);
      } else setQuoteError(true);
    }

    function onVisibility() { if (document.visibilityState === "visible") void update(); }
    void update();
    const timer = window.setInterval(update, 60_000);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      active = false;
      controller?.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [asset, timeframe]);

  const lastBar = candles.at(-1);
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <fieldset className="flex flex-wrap gap-1" aria-label="Chart timeframe">
          {OPTIONS.map((option) => (
            <button key={option.value} type="button" aria-pressed={timeframe === option.value}
              onClick={() => setTimeframe(option.value)}
              className={`min-h-11 rounded-lg px-3 text-sm ${timeframe === option.value ? "bg-accent-soft font-semibold text-accent-hover" : "text-ink-2 hover:bg-hover"}`}>
              {option.label}
            </button>
          ))}
        </fieldset>
        <p className="num text-sm text-ink-2">
          {quote ? <>Spot {usd(Number(quote.price))} · {SOURCE_NAMES[quote.source] ?? quote.source} · {nepalTime(quote.observed_at)} · {quoteError ? "update failed" : quote.freshness.status.replaceAll("_", " ")}</> : "Spot price unavailable"}
        </p>
      </div>
      {candles.length > 0 ? <CandleChart candles={candles} levels={levels} timeframe={timeframe} label={label} /> :
        <p className="py-12 text-ink-2">{loading ? "Loading price history…" : "No price history available."}</p>}
      <p className="mt-3 text-sm leading-relaxed text-ink-2">
        {lastBar ? `Last completed bar starts ${nepalTime(lastBar.bucket_start)} Nepal time. ` : ""}
        Bars are Dukascopy bid prices; spot is a separate quote. Checks every minute while this page is open.
        {candleError ? (candles.length ? " Price history could not be updated; showing the last available bars." : " Price history could not be updated.") : ""}
      </p>
      <p className="mt-1 text-sm text-ink-2">Dotted lines show daily support and resistance from the saved analysis; a solid line marks a watch level.</p>
    </div>
  );
}
