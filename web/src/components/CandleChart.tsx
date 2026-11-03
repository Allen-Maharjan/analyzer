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
  type SeriesType,
  type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useRef } from "react";

type Candle = { bucket_start: string; open: number; high: number; low: number; close: number };
type Level = { id: string; price: number; kind: string; manual: boolean };
export type IndicatorPoint = { bucket_start: string; values: Record<string, number | null> };

/** Things drawn on top of the candles. */
export const OVERLAYS = [
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

export function CandleChart({
  candles,
  levels,
  timeframe,
  label,
  indicators = [],
  overlays = [],
  panels = [],
}: {
  candles: Candle[];
  levels: Level[];
  timeframe: string;
  label: string;
  indicators?: IndicatorPoint[];
  overlays?: OverlayId[];
  panels?: PanelId[];
}) {
  const ref = useRef<HTMLDivElement>(null);
  const legendRef = useRef<HTMLDivElement>(null);
  const shownPanels = indicators.length ? panels : [];
  const shownOverlays = indicators.length ? overlays : [];

  useEffect(() => {
    const el = ref.current;
    const legendEl = legendRef.current;
    if (!el || candles.length === 0) return;
    const chart: IChartApi = createChart(el, {
      height: MAIN_HEIGHT + shownPanels.length * PANEL_HEIGHT,
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
      crosshair: { horzLine: { visible: false } },
      handleScroll: false,
      handleScale: false,
    });

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
    for (const level of levels) {
      candleSeries.createPriceLine({
        price: level.price,
        color: level.manual ? ACCENT : QUIET,
        lineWidth: 1,
        lineStyle: level.manual ? LineStyle.Solid : LineStyle.Dotted,
        axisLabelVisible: false,
        title: "",
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

    chart.timeScale().fitContent();
    const resize = new ResizeObserver(() => {
      chart.applyOptions({ width: el.clientWidth });
      placeLegends();
    });
    resize.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      resize.disconnect();
      chart.remove();
      legendEl?.replaceChildren();
    };
    // shownPanels/shownOverlays are derived from props; join them so the effect reruns on real changes only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, levels, timeframe, indicators, shownPanels.join(), shownOverlays.join()]);

  const described = [...shownOverlays.map((o) => OVERLAYS.find((x) => x.id === o)?.label), ...shownPanels.map((p) => PANEL_SPECS[p].title)].filter(Boolean);
  return (
    <div className="relative">
      <div
        ref={ref}
        className="w-full"
        role="img"
        aria-label={`World ${label} ${timeframe} price candles with support and resistance levels${described.length ? `, plus ${described.join(", ")}` : ""}`}
      />
      <div ref={legendRef} aria-hidden className="pointer-events-none absolute inset-0" />
    </div>
  );
}
