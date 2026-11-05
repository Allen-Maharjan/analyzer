"use client";

import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type IRange,
  type SeriesType,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

import { DrawingLayer, POINTS_NEEDED, TimeAxis, newDrawingId, type Drawing, type DrawingPoint, type Tool } from "@/components/chartDrawings";

type Candle = { bucket_start: string; open: number; high: number; low: number; close: number };
/** A horizontal level: support below the price, resistance above, or the owner's watch level. */
export type ChartLevel = { id: string; price: number; kind: "support" | "resistance" | "watch"; manual: boolean };
export type IndicatorPoint = { bucket_start: string; values: Record<string, number | null> };

/** Things drawn on top of the candles. */
export const OVERLAYS = [
  { id: "levels", label: "Support & resistance" },
  { id: "averages", label: "50 & 200 averages" },
  { id: "bollinger", label: "Bollinger bands" },
] as const;

/** Panels stacked under the candles, one per indicator. */
export const PANELS = [
  { id: "rsi", label: "RSI" },
  { id: "macd", label: "MACD" },
  { id: "stochastic", label: "Stochastic" },
  { id: "adx", label: "ADX" },
  { id: "atr", label: "ATR" },
  { id: "volatility", label: "Volatility" },
] as const;

export type OverlayId = (typeof OVERLAYS)[number]["id"];
export type PanelId = (typeof PANELS)[number]["id"];

// Palette tokens from globals.css. Lightweight Charts draws on canvas, so it needs literal colours.
const INK = "#1c1917";
const INK_2 = "#57534e";
const QUIET = "#a8a29e";
const ACCENT = "#a16207";
const BUY = "#15803d";
const WAIT = "#b91c1c";
const GRID = "#f0f0f1";

const MAIN_HEIGHT = 260;
const PANEL_HEIGHT = 110;

type Line = { field: string; color: string; width?: 1 | 2; style?: LineStyle; name: string; histogram?: boolean };
type PanelSpec = { title: string; lines: Line[]; range?: [number, number]; guides?: number[]; format: (v: number) => string };

const PANEL_SPECS: Record<PanelId, PanelSpec> = {
  rsi: {
    title: "RSI (14)",
    lines: [{ field: "rsi_14", color: INK, width: 2, name: "RSI" }],
    range: [0, 100],
    guides: [30, 70],
    format: (v) => v.toFixed(0),
  },
  macd: {
    title: "MACD (12, 26, 9)",
    lines: [
      { field: "macd_hist", color: QUIET, name: "Histogram", histogram: true },
      { field: "macd", color: INK, width: 2, name: "MACD" },
      { field: "macd_signal", color: ACCENT, name: "Signal" },
    ],
    guides: [0],
    format: (v) => v.toFixed(2),
  },
  stochastic: {
    title: "Stochastic (14, 3, 3)",
    lines: [
      { field: "stoch_k", color: INK, width: 2, name: "%K" },
      { field: "stoch_d", color: ACCENT, name: "%D" },
    ],
    range: [0, 100],
    guides: [20, 80],
    format: (v) => v.toFixed(0),
  },
  adx: {
    title: "ADX (14)",
    lines: [
      { field: "adx_14", color: INK, width: 2, name: "ADX" },
      { field: "plus_di", color: BUY, name: "+DI buyers" },
      { field: "minus_di", color: WAIT, name: "−DI sellers" },
    ],
    guides: [25],
    format: (v) => v.toFixed(0),
  },
  atr: {
    title: "ATR (14)",
    lines: [{ field: "atr_14", color: INK, width: 2, name: "ATR" }],
    format: (v) => `$${v < 10 ? v.toFixed(2) : v.toFixed(0)}`,
  },
  volatility: {
    title: "Volatility (20, yearly)",
    lines: [{ field: "realized_vol", color: INK, width: 2, name: "Volatility" }],
    format: (v) => `${(v * 100).toFixed(0)}%`,
  },
};

const OVERLAY_LINES: Record<OverlayId, Line[]> = {
  levels: [], // drawn as price lines, see below
  averages: [
    { field: "sma_50", color: ACCENT, width: 2, name: "50 avg" },
    { field: "sma_200", color: INK_2, width: 2, name: "200 avg" },
  ],
  bollinger: [
    { field: "bb_upper", color: QUIET, style: LineStyle.Dashed, name: "Upper band" },
    { field: "bb_middle", color: QUIET, style: LineStyle.Dotted, name: "Middle" },
    { field: "bb_lower", color: QUIET, style: LineStyle.Dashed, name: "Lower band" },
  ],
};

const time = (iso: string) => (Date.parse(iso) / 1000) as UTCTimestamp;

/** Drawing controls for the full-screen chart. Without them the chart is fixed and read-only. */
export type ChartEditor = {
  tool: Tool;
  selectedId: string | null;
  onAdd: (drawing: Drawing) => void;
  onSelect: (id: string | null) => void;
};

const NO_DRAWINGS: Drawing[] = [];

export function CandleChart({
  candles,
  levels,
  timeframe,
  label,
  indicators = [],
  overlays = [],
  panels = [],
  drawings = NO_DRAWINGS,
  editor,
  fill = false,
}: {
  candles: Candle[];
  levels: ChartLevel[];
  timeframe: string;
  label: string;
  indicators?: IndicatorPoint[];
  overlays?: OverlayId[];
  panels?: PanelId[];
  drawings?: Drawing[];
  editor?: ChartEditor;
  /** Fill the parent's height instead of using the fixed height. */
  fill?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const legendRef = useRef<HTMLDivElement>(null);
  const shownPanels = indicators.length ? panels : [];
  const shownOverlays = indicators.length ? overlays : [];
  const interactive = editor != null;
  const chartRef = useRef<IChartApi | null>(null);
  const layerRef = useRef<DrawingLayer | null>(null);
  // Latest values for event handlers, so a new tool or drawing doesn't rebuild the chart.
  const editorRef = useRef(editor);
  const drawingsRef = useRef(drawings);
  useEffect(() => {
    editorRef.current = editor;
    drawingsRef.current = drawings;
  });
  // Keep the zoom and scroll position when fresh bars arrive each minute.
  const viewRef = useRef<{ timeframe: string; range: IRange<Time> } | null>(null);
  const cancelDrawRef = useRef<() => void>(() => {});

  useEffect(() => {
    const el = ref.current;
    const legendEl = legendRef.current;
    if (!el || candles.length === 0) return;
    const chart: IChartApi = createChart(el, {
      ...(fill ? { autoSize: true } : { height: MAIN_HEIGHT + shownPanels.length * PANEL_HEIGHT }),
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#5f5f67",
        attributionLogo: false,
        fontSize: 11,
        panes: { separatorColor: "#e7e5e4", separatorHoverColor: "#e7e5e4", enableResize: false },
      },
      grid: { vertLines: { visible: false }, horzLines: { color: GRID } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: timeframe !== "1D" },
      crosshair: { horzLine: { visible: interactive } },
      handleScroll: interactive,
      handleScale: interactive,
    });
    chartRef.current = chart;

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: BUY,
      downColor: WAIT,
      wickUpColor: BUY,
      wickDownColor: WAIT,
      borderVisible: false,
      priceLineVisible: false,
    });
    candleSeries.setData(
      candles.map((c) => ({ time: time(c.bucket_start), open: Number(c.open), high: Number(c.high), low: Number(c.low), close: Number(c.close) })),
    );
    const axis = new TimeAxis(chart, candles.map((c) => time(c.bucket_start)));
    const layer = new DrawingLayer(axis);
    layer.set(drawingsRef.current, editorRef.current?.selectedId ?? null, null);
    candleSeries.attachPrimitive(layer);
    layerRef.current = layer;
    // Support (green) and resistance (red) as dashed lines labelled on the price axis; the
    // owner's watch level as a solid ochre line. Toggled with the "Support & resistance" chip.
    const LEVEL_STYLE = {
      support: { color: BUY, style: LineStyle.Dashed, title: "S" },
      resistance: { color: WAIT, style: LineStyle.Dashed, title: "R" },
      watch: { color: ACCENT, style: LineStyle.Solid, title: "Watch" },
    } as const;
    const showLevels = overlays.includes("levels");
    const rank = { support: 0, resistance: 0, watch: 0 };
    for (const level of levels) {
      if (!showLevels && level.kind !== "watch") continue;
      const look = LEVEL_STYLE[level.kind] ?? LEVEL_STYLE.support;
      rank[level.kind] += 1; // levels arrive nearest first: S1 is the closest support, R1 the closest resistance
      candleSeries.createPriceLine({
        price: level.price,
        color: look.color,
        lineWidth: level.kind === "watch" ? 1 : 2,
        lineStyle: look.style,
        axisLabelVisible: true,
        title: level.kind === "watch" ? look.title : `${look.title}${rank[level.kind]}`,
      });
    }

    // Legend entries: each pane's lines, with the value under the crosshair (or the latest).
    type Entry = { pane: number; line: Line; series: ISeriesApi<SeriesType>; format: (v: number) => string; latest: number | null };
    const entries: Entry[] = [];
    const pointsFor = (field: string) =>
      indicators.flatMap((p) => (p.values[field] == null ? [] : [{ time: time(p.bucket_start), value: p.values[field] as number }]));

    const addLine = (pane: number, line: Line, format: (v: number) => string, range?: [number, number]) => {
      const data = pointsFor(line.field);
      const common = {
        priceLineVisible: false,
        lastValueVisible: false,
        priceFormat: { type: "custom" as const, formatter: format, minMove: 0.0001 },
        autoscaleInfoProvider: range ? () => ({ priceRange: { minValue: range[0], maxValue: range[1] } }) : undefined,
      };
      let series: ISeriesApi<SeriesType>;
      if (line.histogram) {
        const hist = chart.addSeries(HistogramSeries, { ...common, base: 0 }, pane);
        hist.setData(data.map((d) => ({ ...d, color: d.value >= 0 ? "rgb(21 128 61 / 0.35)" : "rgb(185 28 28 / 0.35)" })));
        series = hist;
      } else {
        const ln = chart.addSeries(
          LineSeries,
          { ...common, color: line.color, lineWidth: line.width ?? 1, lineStyle: line.style ?? LineStyle.Solid, crosshairMarkerRadius: 3 },
          pane,
        );
        ln.setData(data);
        series = ln;
      }
      entries.push({ pane, line, series, format, latest: data.at(-1)?.value ?? null });
      return series;
    };

    for (const id of shownOverlays) {
      for (const line of OVERLAY_LINES[id]) addLine(0, line, (v) => `$${v.toFixed(2)}`);
    }
    shownPanels.forEach((id, i) => {
      const spec = PANEL_SPECS[id];
      spec.lines.forEach((line, j) => {
        const series = addLine(i + 1, line, spec.format, spec.range);
        if (j === 0) {
          for (const g of spec.guides ?? []) {
            series.createPriceLine({ price: g, color: QUIET, lineWidth: 1, lineStyle: LineStyle.Dashed, axisLabelVisible: false, title: "" });
          }
        }
      });
    });

    // Stretch factors share the chart's height in proportion; fixed pixel heights get overridden on layout.
    chart.panes().forEach((pane, i) => pane.setStretchFactor(i === 0 ? MAIN_HEIGHT : PANEL_HEIGHT));

    // HTML legends, one per pane, placed at the pane's top-left corner.
    const legends: HTMLDivElement[] = [];
    if (legendEl) {
      legendEl.replaceChildren();
      const groups = [{ title: "", pane: 0 }, ...shownPanels.map((id, i) => ({ title: PANEL_SPECS[id].title, pane: i + 1 }))];
      for (const g of groups) {
        const box = document.createElement("div");
        box.className = "pointer-events-none absolute left-1 flex max-w-[calc(100%-4.5rem)] flex-wrap items-center gap-x-3 gap-y-0.5 rounded-md px-1.5 py-0.5 text-[11px] leading-4 text-ink-2";
        box.style.background = "rgb(255 255 255 / 0.88)";
        box.dataset.pane = String(g.pane);
        legendEl.appendChild(box);
        legends.push(box);
      }
    }
    const placeLegends = () => {
      let top = 0;
      chart.panes().forEach((pane, i) => {
        if (legends[i]) legends[i].style.top = `${top + 4}px`;
        top += pane.getHeight() + 1;
      });
    };
    const renderLegends = (values?: Map<ISeriesApi<SeriesType>, number | null>) => {
      legends.forEach((box, paneIndex) => {
        const title = paneIndex === 0 ? "" : PANEL_SPECS[shownPanels[paneIndex - 1]].title;
        const parts = entries
          .filter((e) => e.pane === paneIndex)
          .map((e) => {
            const v = values?.has(e.series) ? values.get(e.series) : e.latest;
            const swatch = e.line.histogram ? "" : `<span style="display:inline-block;width:10px;height:2px;background:${e.line.color};vertical-align:middle;margin-right:4px"></span>`;
            return `<span class="num whitespace-nowrap">${swatch}${e.line.name} <b class="font-medium text-ink">${v == null ? "–" : e.format(v)}</b></span>`;
          });
        box.innerHTML = (title ? `<span class="font-semibold text-ink">${title}</span>` : "") + parts.join("");
        box.style.display = parts.length || title ? "" : "none";
      });
    };
    renderLegends();
    placeLegends();
    // Pane sizes settle after the first layout pass.
    const frame = requestAnimationFrame(placeLegends);

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) return renderLegends();
      const values = new Map<ISeriesApi<SeriesType>, number | null>();
      for (const e of entries) {
        const d = param.seriesData.get(e.series) as { value?: number } | undefined;
        values.set(e.series, d?.value ?? null);
      }
      renderLegends(values);
    });

    const saved = viewRef.current;
    if (interactive && saved && saved.timeframe === timeframe) chart.timeScale().setVisibleRange(saved.range);
    else chart.timeScale().fitContent();
    const resize = new ResizeObserver(() => {
      if (!fill) chart.applyOptions({ width: el.clientWidth });
      placeLegends();
    });
    resize.observe(el);

    // Drawing: drag from start to end, or tap the start and then the end. A horizontal line takes one tap.
    let start: DrawingPoint | null = null;
    let phase: "idle" | "dragging" | "awaiting" = "idle";
    let downAt = { x: 0, y: 0 };
    const local = (e: PointerEvent) => {
      const box = el.getBoundingClientRect();
      return { x: e.clientX - box.left, y: e.clientY - box.top };
    };
    const inPricePane = (p: { x: number; y: number }) => {
      const size = chart.paneSize(0);
      return p.x >= 0 && p.x <= size.width && p.y >= 0 && p.y <= size.height;
    };
    const pointAt = (p: { x: number; y: number }): DrawingPoint | null => {
      const t = axis.time(p.x);
      const v = candleSeries.coordinateToPrice(p.y);
      return t == null || v == null || v <= 0 ? null : { time: t, price: Math.round(v * 100) / 100 };
    };
    const kind = () => {
      const tool = editorRef.current?.tool;
      return tool && tool !== "select" ? tool : null;
    };
    const finish = (end: DrawingPoint) => {
      const k = kind();
      if (k && start) editorRef.current?.onAdd({ id: newDrawingId(), kind: k, points: [start, end] });
      cancel();
    };
    const cancel = () => {
      start = null;
      phase = "idle";
      layer.setPreview(null);
    };
    cancelDrawRef.current = cancel;
    const onDown = (e: PointerEvent) => {
      const k = kind();
      const p = local(e);
      if (!k || !inPricePane(p)) return;
      const point = pointAt(p);
      if (!point) return;
      e.preventDefault();
      e.stopPropagation();
      if (POINTS_NEEDED[k] === 1) {
        editorRef.current?.onAdd({ id: newDrawingId(), kind: k, points: [point] });
        return;
      }
      if (phase === "awaiting" && start) return finish(point);
      el.setPointerCapture(e.pointerId);
      start = point;
      downAt = p;
      phase = "dragging";
      layer.setPreview({ id: "preview", kind: k, points: [point, point] });
    };
    const onMove = (e: PointerEvent) => {
      const k = kind();
      if (!k || !start || phase === "idle") return;
      const point = pointAt(local(e));
      if (point) layer.setPreview({ id: "preview", kind: k, points: [start, point] });
    };
    const onUp = (e: PointerEvent) => {
      if (phase !== "dragging" || !start) return;
      const p = local(e);
      if (Math.hypot(p.x - downAt.x, p.y - downAt.y) < 6) {
        phase = "awaiting"; // a tap: wait for the end point
        return;
      }
      const point = pointAt(p);
      if (point) finish(point);
      else cancel();
    };
    // In move mode, a tap selects the nearest drawing, or clears the selection.
    const onClick = (param: MouseEventParams<Time>) => {
      const ed = editorRef.current;
      if (!ed || ed.tool !== "select" || !param.point) return;
      ed.onSelect(layer.hit(param.point, chart.paneSize(0).width, window.matchMedia("(pointer: coarse)").matches ? 14 : 8));
    };
    if (interactive) {
      el.addEventListener("pointerdown", onDown, true);
      el.addEventListener("pointermove", onMove);
      el.addEventListener("pointerup", onUp);
      el.addEventListener("pointercancel", cancel);
      chart.subscribeClick(onClick);
    }

    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      if (interactive) {
        el.removeEventListener("pointerdown", onDown, true);
        el.removeEventListener("pointermove", onMove);
        el.removeEventListener("pointerup", onUp);
        el.removeEventListener("pointercancel", cancel);
        const range = chart.timeScale().getVisibleRange();
        viewRef.current = range ? { timeframe, range } : null;
      }
      cancelDrawRef.current = () => {};
      chartRef.current = null;
      layerRef.current = null;
      chart.remove();
      legendEl?.replaceChildren();
    };
    // shownPanels/shownOverlays are derived from props; join them so the effect reruns on real changes only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, levels, timeframe, indicators, shownPanels.join(), shownOverlays.join(), overlays.includes("levels"), interactive, fill]);

  // New or removed drawings and selection: redraw without rebuilding the chart.
  useEffect(() => {
    layerRef.current?.set(drawings, editor?.selectedId ?? null);
  }, [drawings, editor?.selectedId]);

  // Moving and zooming only in move mode; while drawing, a drag draws instead. Switching tools drops a half-drawn line.
  const tool = editor?.tool ?? "select";
  useEffect(() => {
    cancelDrawRef.current();
    if (!interactive) return;
    chartRef.current?.applyOptions({ handleScroll: tool === "select", handleScale: tool === "select" });
  }, [tool, interactive]);

  const described = [...shownOverlays.map((o) => OVERLAYS.find((x) => x.id === o)?.label), ...shownPanels.map((p) => PANEL_SPECS[p].title)].filter(Boolean);
  return (
    <div className={fill ? "relative h-full" : "relative"}>
      <div
        ref={ref}
        className={fill ? "h-full w-full" : "w-full"}
        style={interactive && tool !== "select" ? { touchAction: "none", cursor: "crosshair" } : undefined}
        role="img"
        aria-label={`World ${label} ${timeframe} price candles with support and resistance levels${described.length ? `, plus ${described.join(", ")}` : ""}${drawings.length ? `, and ${drawings.length} line${drawings.length === 1 ? "" : "s"} you drew` : ""}`}
      />
      <div ref={legendRef} aria-hidden className="pointer-events-none absolute inset-0" />
    </div>
  );
}
