"use client";

import { useEffect, useState } from "react";

import { CandleChart, OVERLAYS, PANELS, type ChartLevel, type IndicatorPoint, type OverlayId, type PanelId } from "@/components/CandleChart";
import { nepalTime, usd } from "@/lib/format";

type Candle = { bucket_start: string; open: number; high: number; low: number; close: number };
type Quote = { price: string | number; source: string; observed_at: string; freshness: { status: string } };
type Timeframe = "15m" | "1h" | "1D";
const OPTIONS: { value: Timeframe; label: string }[] = [
  { value: "15m", label: "15 minutes" },
  { value: "1h", label: "1 hour" },
  { value: "1D", label: "1 day" },
];
const SOURCE_NAMES: Record<string, string> = { gold_api: "Gold API", swissquote: "Swissquote" };
const DEFAULT_OVERLAYS: OverlayId[] = ["levels", "averages"];
const DEFAULT_PANELS: PanelId[] = ["rsi", "macd"];
const STORAGE_KEY = "chart-indicators-v2"; // v2 added support & resistance (on by default)

/** Remember which indicators the owner turned on. Browser storage can be unavailable; then use defaults. */
function loadChoice(): { overlays: OverlayId[]; panels: PanelId[] } {
  try {
    const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "null");
    if (saved && Array.isArray(saved.overlays) && Array.isArray(saved.panels)) {
      return {
        overlays: saved.overlays.filter((o: string) => OVERLAYS.some((x) => x.id === o)),
        panels: saved.panels.filter((p: string) => PANELS.some((x) => x.id === p)),
      };
    }
  } catch {}
  return { overlays: DEFAULT_OVERLAYS, panels: DEFAULT_PANELS };
}

function Chip({ on, label, onClick }: { on: boolean; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`inline-flex min-h-9 items-center rounded-full border px-3 text-sm transition-colors ${
        on ? "border-accent/40 bg-accent-soft font-medium text-accent-hover" : "border-line bg-panel text-ink-2 hover:bg-hover hover:text-ink"
      }`}
    >
      {label}
    </button>
  );
}

export function WorldChart({ asset, label, initialCandles, levels }: {
  asset: string; label: string; initialCandles: Candle[]; levels: Record<Timeframe, ChartLevel[]>;
}) {
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [series, setSeries] = useState<{ timeframe: Timeframe; candles: Candle[] }>({ timeframe: "15m", candles: initialCandles });
  const candles = series.timeframe === timeframe ? series.candles : [];
  const [quote, setQuote] = useState<Quote | null>(null);
  const [candleError, setCandleError] = useState(false);
  const [quoteError, setQuoteError] = useState(false);
  const [loading, setLoading] = useState(false);
  const [indicators, setIndicators] = useState<{ timeframe: Timeframe; points: IndicatorPoint[] }>({ timeframe: "15m", points: [] });
  const [indicatorError, setIndicatorError] = useState(false);
  const [overlays, setOverlays] = useState<OverlayId[]>(DEFAULT_OVERLAYS);
  const [panels, setPanels] = useState<PanelId[]>(DEFAULT_PANELS);

  useEffect(() => {
    const saved = loadChoice();
    setOverlays(saved.overlays);
    setPanels(saved.panels);
  }, []);

  function save(next: { overlays: OverlayId[]; panels: PanelId[] }) {
    setOverlays(next.overlays);
    setPanels(next.panels);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {}
  }
  const toggle = <T,>(list: T[], id: T) => (list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);

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
      const [bars, spot, ind] = await Promise.allSettled([
        fetch(`/api/market/candles?${query}`, { cache: "no-store", signal: controller.signal }).then(async (r) => {
          if (!r.ok) throw new Error("candles unavailable");
          return r.json() as Promise<{ candles: Candle[] }>;
        }),
        fetch(`/api/market/quote?${quoteQuery}`, { cache: "no-store", signal: controller.signal }).then(async (r) => {
          if (!r.ok) throw new Error("quote unavailable");
          return r.json() as Promise<Quote>;
        }),
        fetch(`/api/market/indicators?${query}`, { cache: "no-store", signal: controller.signal }).then(async (r) => {
          if (!r.ok) throw new Error("indicators unavailable");
          return r.json() as Promise<{ points: IndicatorPoint[] }>;
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
      if (ind.status === "fulfilled") {
        setIndicators({ timeframe, points: ind.value.points });
        setIndicatorError(false);
      } else setIndicatorError(true);
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
  const points = indicators.timeframe === timeframe ? indicators.points : [];
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
      <div className="mb-3 space-y-2">
        <div role="group" aria-label="Draw on the price chart" className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs text-ink-2">On the chart</span>
          {OVERLAYS.map((o) => (
            <Chip key={o.id} label={o.label} on={overlays.includes(o.id)} onClick={() => save({ overlays: toggle(overlays, o.id), panels })} />
          ))}
        </div>
        <div role="group" aria-label="Indicator panels under the chart" className="flex flex-wrap items-center gap-1.5">
          <span className="mr-1 text-xs text-ink-2">Panels below</span>
          {PANELS.map((p) => (
            <Chip key={p.id} label={p.label} on={panels.includes(p.id)} onClick={() => save({ overlays, panels: toggle(panels, p.id) })} />
          ))}
        </div>
      </div>
      {candles.length > 0 ? (
        <CandleChart
          candles={candles}
          levels={levels[timeframe] ?? []}
          timeframe={timeframe}
          label={label}
          indicators={points}
          overlays={overlays}
          panels={PANELS.map((p) => p.id).filter((id) => panels.includes(id))}
        />
      ) : (
        <p className="py-12 text-ink-2">{loading ? "Loading price history…" : "No price history available."}</p>
      )}
      <p className="mt-3 text-sm leading-relaxed text-ink-2">
        {lastBar ? `Last completed bar starts ${nepalTime(lastBar.bucket_start)} Nepal time. ` : ""}
        Bars are Dukascopy bid prices; spot is a separate quote. Checks every minute while this page is open.
        {candleError ? (candles.length ? " Price history could not be updated; showing the last available bars." : " Price history could not be updated.") : ""}
        {indicatorError && candles.length ? " Indicators could not be loaded right now." : ""}
      </p>
      <p className="mt-1 text-sm text-ink-2">
        Green dashed lines (S1, S2) are support, prices where falls have tended to stop; red dashed lines (R1, R2) are resistance,
        where rises have tended to stall. S1 and R1 are the nearest, for the timeframe shown. A solid ochre line marks your watch level. Indicators use the same
        bars as the chart; dashed lines in the panels mark their usual thresholds (for example RSI 30 and 70). Tap or hover to read values.
      </p>
    </div>
  );
}
