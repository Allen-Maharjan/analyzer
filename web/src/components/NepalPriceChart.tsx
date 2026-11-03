"use client";

import { ColorType, LineSeries, createChart, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

type Point = { date: string; price: number };

/** Nepal's published price over recent updates, so today's number has context. */
export function NepalPriceChart({ points }: { points: Point[] }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || points.length < 2) return;
    const chart = createChart(el, {
      height: 140,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#5f5f67", attributionLogo: false, fontSize: 11 },
      grid: { vertLines: { visible: false }, horzLines: { visible: false } },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
      handleScroll: false,
      handleScale: false,
      crosshair: { horzLine: { visible: false } },
      // Lakh notation for gold (Rs 2,75,000 -> 2.75L); plain rupees for silver (Rs 3,675).
      localization: { priceFormatter: (p: number) => (p >= 100000 ? `${(p / 100000).toFixed(2)}L` : Math.round(p).toLocaleString("en-IN")) },
    });
    const series = chart.addSeries(LineSeries, { color: "#a16207", lineWidth: 2, priceLineVisible: false, lastValueVisible: false });
    series.setData(points.map((p) => ({ time: (Date.parse(`${p.date}T00:00:00Z`) / 1000) as UTCTimestamp, value: p.price })));
    chart.timeScale().fitContent();
    const resize = new ResizeObserver(() => chart.applyOptions({ width: el.clientWidth }));
    resize.observe(el);
    return () => {
      resize.disconnect();
      chart.remove();
    };
  }, [points]);

  if (points.length < 2) return null;
  const first = points[0].price;
  const last = points[points.length - 1].price;
  return (
    <figure>
      <div ref={ref} className="w-full" aria-hidden />
      <figcaption className="sr-only">
        Nepal metal price over the last {points.length} updates, from Rs {first} to Rs {last} per tola.
      </figcaption>
    </figure>
  );
}
