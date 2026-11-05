"use client";

import { Eraser, Maximize2, Minus, MousePointer2, Rows3, Square, Trash2, TrendingUp, X, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { CandleChart, OVERLAYS, PANELS, type ChartLevel, type IndicatorPoint, type OverlayId, type PanelId } from "@/components/CandleChart";
import type { Drawing, Tool } from "@/components/chartDrawings";
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

const TOOLS: { id: Tool; label: string; icon: LucideIcon; hint: string }[] = [
  { id: "select", label: "Move", icon: MousePointer2, hint: "Drag to move the chart; pinch or scroll to zoom. Tap a line you drew to select it." },
  { id: "trend", label: "Trend line", icon: TrendingUp, hint: "Drag from start to end, or tap the start and then the end." },
  { id: "horizontal", label: "Price line", icon: Minus, hint: "Tap the price you want to mark." },
  { id: "rectangle", label: "Box", icon: Square, hint: "Drag from one corner to the opposite corner." },
  { id: "fib", label: "Fibonacci", icon: Rows3, hint: "Drag from a low to a high (or high to low) to see the usual pull-back levels." },
];

type SaveState = "idle" | "saving" | "saved" | "error";

function ToolButton({ on, label, icon: Icon, onClick, disabled }: { on?: boolean; label: string; icon: LucideIcon; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-lg px-2.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        on ? "bg-accent-soft font-semibold text-accent-hover" : "text-ink-2 hover:bg-hover hover:text-ink"
      }`}
    >
      <Icon aria-hidden size={18} strokeWidth={1.75} />
      <span className="hidden lg:inline">{label}</span>
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
  const [expanded, setExpanded] = useState(false);
  const [tool, setTool] = useState<Tool>("select");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [drawingsError, setDrawingsError] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const saveSeq = useRef(0);

  useEffect(() => {
    let active = true;
    fetch(`/api/settings/drawings?${new URLSearchParams({ asset })}`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error("drawings unavailable");
        return (await r.json()) as { drawings: Drawing[] };
      })
      .then((body) => active && setDrawings(body.drawings))
      .catch(() => active && setDrawingsError(true));
    return () => {
      active = false;
    };
  }, [asset]);

  /** Save the whole set; a slower, older save never overwrites a newer one's status. */
  async function persist(next: Drawing[]) {
    setDrawings(next);
    const seq = ++saveSeq.current;
    setSaveState("saving");
    try {
      const r = await fetch(`/api/settings/drawings?${new URLSearchParams({ asset })}`, {
        method: "PUT",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ drawings: next }),
      });
      if (seq === saveSeq.current) setSaveState(r.ok ? "saved" : "error");
    } catch {
      if (seq === saveSeq.current) setSaveState("error");
    }
  }

  function addDrawing(d: Drawing) {
    void persist([...drawings, d]);
    setSelectedId(d.id);
    setTool("select");
  }

  function deleteSelected() {
    if (!selectedId) return;
    void persist(drawings.filter((d) => d.id !== selectedId));
    setSelectedId(null);
  }

  function clearAll() {
    if (!confirmClear) {
      setConfirmClear(true);
      window.setTimeout(() => setConfirmClear(false), 4000);
      return;
    }
    setConfirmClear(false);
    setSelectedId(null);
    void persist([]);
  }

  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (expanded && !dialog.open) dialog.showModal();
    if (!expanded && dialog.open) dialog.close();
  }, [expanded]);

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
      const query = new URLSearchParams({ asset, timeframe, bars: expanded ? "long" : "short" });
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
  }, [asset, timeframe, expanded]);

  const lastBar = candles.at(-1);
  const points = indicators.timeframe === timeframe ? indicators.points : [];
  const shownPanels = PANELS.map((p) => p.id).filter((id) => panels.includes(id));
  const hint = TOOLS.find((t) => t.id === tool)?.hint ?? "";

  const timeframeButtons = (
    <fieldset className="flex flex-wrap gap-1" aria-label="Chart timeframe">
      {OPTIONS.map((option) => (
        <button key={option.value} type="button" aria-pressed={timeframe === option.value}
          onClick={() => setTimeframe(option.value)}
          className={`min-h-11 rounded-lg px-3 text-sm ${timeframe === option.value ? "bg-accent-soft font-semibold text-accent-hover" : "text-ink-2 hover:bg-hover"}`}>
          {option.label}
        </button>
      ))}
    </fieldset>
  );
  const spot = (
    <p className="num text-sm text-ink-2">
      {quote ? <>Spot {usd(Number(quote.price))} · {SOURCE_NAMES[quote.source] ?? quote.source} · {nepalTime(quote.observed_at)} · {quoteError ? "update failed" : quote.freshness.status.replaceAll("_", " ")}</> : "Spot price unavailable"}
    </p>
  );
  const chips = (wrap: boolean) => (
    <div className={wrap ? "space-y-2" : "flex gap-4 overflow-x-auto pb-1"}>
      <div role="group" aria-label="Draw on the price chart" className={`flex items-center gap-1.5 ${wrap ? "flex-wrap" : "shrink-0"}`}>
        <span className="mr-1 shrink-0 text-xs text-ink-2">On the chart</span>
        {OVERLAYS.map((o) => (
          <Chip key={o.id} label={o.label} on={overlays.includes(o.id)} onClick={() => save({ overlays: toggle(overlays, o.id), panels })} />
        ))}
      </div>
      <div role="group" aria-label="Indicator panels under the chart" className={`flex items-center gap-1.5 ${wrap ? "flex-wrap" : "shrink-0"}`}>
        <span className="mr-1 shrink-0 text-xs text-ink-2">Panels below</span>
        {PANELS.map((p) => (
          <Chip key={p.id} label={p.label} on={panels.includes(p.id)} onClick={() => save({ overlays, panels: toggle(panels, p.id) })} />
        ))}
      </div>
    </div>
  );
  const saveText =
    saveState === "saving" ? "Saving your lines…"
    : saveState === "error" ? "Your lines couldn't be saved. They stay on screen and will save with your next change."
    : drawingsError ? "Your saved lines couldn't be loaded. New lines may replace them."
    : saveState === "saved" ? "Lines saved. They show on every timeframe and device."
    : "";

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        {timeframeButtons}
        <div className="flex flex-wrap items-center gap-2">
          {spot}
          <button
            type="button"
            onClick={() => setExpanded(true)}
            className="inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-line bg-panel px-3 text-sm font-medium text-ink hover:bg-hover"
          >
            <Maximize2 aria-hidden size={16} strokeWidth={1.75} />
            Full screen and draw
          </button>
        </div>
      </div>
      <div className="mb-3">{chips(true)}</div>
      {candles.length > 0 && !expanded ? (
        <CandleChart
          candles={candles}
          levels={levels[timeframe] ?? []}
          timeframe={timeframe}
          label={label}
          indicators={points}
          overlays={overlays}
          panels={shownPanels}
          drawings={drawings}
        />
      ) : (
        <p className="py-12 text-ink-2">{expanded ? "The chart is open in full screen." : loading ? "Loading price history…" : "No price history available."}</p>
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
        {drawings.length ? " Blue lines are the ones you drew in full screen; they are your notes and don't change the advice." : ""}
      </p>

      <dialog
        ref={dialogRef}
        aria-label={`World ${label} price chart, full screen`}
        onClose={() => {
          setExpanded(false);
          setTool("select");
          setSelectedId(null);
        }}
        onCancel={(e) => {
          // Escape first drops the drawing tool, then closes.
          if (tool !== "select") {
            e.preventDefault();
            setTool("select");
          }
        }}
        onKeyDown={(e) => {
          if ((e.key === "Delete" || e.key === "Backspace") && selectedId) {
            e.preventDefault();
            deleteSelected();
          }
        }}
        className="fixed inset-0 m-0 h-dvh max-h-none w-screen max-w-none bg-panel p-0 text-ink backdrop:bg-ink/40"
      >
        {expanded && (
          <div className="flex h-full flex-col gap-2 px-3 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:px-5">
            <div className="flex items-center justify-between gap-2">
              <div className="min-w-0">
                <h2 className="text-base font-semibold capitalize">World {label} price</h2>
                {spot}
              </div>
              <button
                type="button"
                onClick={() => setExpanded(false)}
                aria-label="Close full screen"
                className="inline-flex min-h-11 min-w-11 items-center justify-center gap-1.5 rounded-lg border border-line px-3 text-sm font-medium text-ink hover:bg-hover"
              >
                <X aria-hidden size={18} strokeWidth={1.75} />
                <span className="hidden sm:inline">Close</span>
              </button>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1">
              {timeframeButtons}
              <div className="flex flex-wrap items-center gap-1">
                <div role="group" aria-label="Drawing tools" className="flex items-center gap-0.5 rounded-xl border border-line p-0.5">
                  {TOOLS.map((t) => (
                    <ToolButton key={t.id} label={t.label} icon={t.icon} on={tool === t.id} onClick={() => { setTool(t.id); setSelectedId(null); }} />
                  ))}
                </div>
                <ToolButton label="Delete selected line" icon={Trash2} disabled={!selectedId} onClick={deleteSelected} />
                <button
                  type="button"
                  disabled={!drawings.length}
                  onClick={clearAll}
                  title="Delete all lines you drew"
                  className={`inline-flex min-h-11 items-center gap-1.5 rounded-lg px-2.5 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                    confirmClear ? "bg-wait-soft font-semibold text-wait" : "text-ink-2 hover:bg-hover hover:text-ink"
                  }`}
                >
                  <Eraser aria-hidden size={18} strokeWidth={1.75} />
                  <span className={confirmClear ? "" : "hidden lg:inline"}>{confirmClear ? "Tap again to delete all" : "Clear all"}</span>
                </button>
              </div>
            </div>
            {chips(false)}
            <div className="relative min-h-0 flex-1">
              {candles.length > 0 ? (
                <CandleChart
                  candles={candles}
                  levels={levels[timeframe] ?? []}
                  timeframe={timeframe}
                  label={label}
                  indicators={points}
                  overlays={overlays}
                  panels={shownPanels}
                  drawings={drawings}
                  editor={{ tool, selectedId, onAdd: addDrawing, onSelect: setSelectedId }}
                  fill
                />
              ) : (
                <p className="py-12 text-ink-2">{loading ? "Loading price history…" : "No price history available."}</p>
              )}
            </div>
            <p className="text-sm text-ink-2" aria-live="polite">
              {hint}
              {saveText ? <span className={saveState === "error" || drawingsError ? " text-wait" : ""}> {saveText}</span> : null}
            </p>
          </div>
        )}
      </dialog>
    </div>
  );
}
