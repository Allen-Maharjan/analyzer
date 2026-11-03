"use client";

import { CandlestickSeries, ColorType, LineStyle, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

type Candle = { bucket_start: string; open: number; high: number; low: number; close: number };
type Level = { id: string; price: number; kind: string; manual: boolean };

export function CandleChart({ candles, levels, timeframe, label }: { candles: Candle[]; levels: Level[]; timeframe: string; label: string }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || candles.length === 0) return;
    const chart = createChart(el, {
      height: 260,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#5f5f67", attributionLogo: false, fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { color: "#f0f0f1" } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, timeVisible: timeframe !== "1D" },
      handleScroll: false,
      handleScale: false,
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#15803d",
      downColor: "#b91c1c",
      wickUpColor: "#15803d",
      wickDownColor: "#b91c1c",
      borderVisible: false,
    });
    series.setData(
      candles.map((c) => ({
        time: (Date.parse(c.bucket_start) / 1000) as UTCTimestamp,
        open: Number(c.open),
        high: Number(c.high),
        low: Number(c.low),
        close: Number(c.close),
      })),
    );
    for (const level of levels) {
      series.createPriceLine({
        price: level.price,
        color: level.manual ? "#a16207" : "#a8a29e",
        lineWidth: 1,
        lineStyle: level.manual ? LineStyle.Solid : LineStyle.Dotted,
        axisLabelVisible: false,
        title: "",
      });
    }
    chart.timeScale().fitContent();
    const resize = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    resize.observe(el);
    return () => {
      resize.disconnect();
      chart.remove();
    };
  }, [candles, levels, timeframe]);

  return <div ref={ref} className="w-full" role="img" aria-label={`World ${label} ${timeframe} price candles with support and resistance levels`} />;
}
