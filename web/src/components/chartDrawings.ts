import type {
  IChartApi,
  IPrimitivePaneRenderer,
  IPrimitivePaneView,
  ISeriesApi,
  ISeriesPrimitive,
  Logical,
  SeriesAttachedParameter,
  SeriesType,
  Time,
} from "lightweight-charts";

/** Lines the owner draws on the chart, anchored by time (Unix seconds) and price (US$). */
export type DrawingKind = "trend" | "horizontal" | "rectangle" | "fib";
export type DrawingPoint = { time: number; price: number };
export type Drawing = { id: string; kind: DrawingKind; points: DrawingPoint[] };
export type Tool = "select" | DrawingKind;

export const POINTS_NEEDED: Record<DrawingKind, number> = { trend: 2, horizontal: 1, rectangle: 2, fib: 2 };
export const FIB_RATIOS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];

// Blue keeps drawings apart from the green/red support and resistance lines and the ochre watch level.
const COLOR = "#1d4ed8";
const FILL = "rgb(29 78 216 / 0.08)";
const HIT_PX = 8;

export function newDrawingId(): string {
  // crypto.randomUUID needs HTTPS; the local Docker app can be opened over plain HTTP.
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

type Px = { x: number; y: number };

/**
 * Converts between bar times and screen x. Times between bars, before the first bar or after the last
 * are interpolated by bar position, so a line drawn on one timeframe lands in the right place on another.
 */
export class TimeAxis {
  constructor(
    private chart: IChartApi,
    private times: number[],
  ) {}

  private logicalOf(t: number): number | null {
    const ts = this.times;
    const n = ts.length;
    if (n === 0) return null;
    if (n === 1) return 0;
    if (t <= ts[0]) return (t - ts[0]) / (ts[1] - ts[0]);
    if (t >= ts[n - 1]) return n - 1 + (t - ts[n - 1]) / (ts[n - 1] - ts[n - 2]);
    let lo = 0;
    let hi = n - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (ts[mid] <= t) lo = mid;
      else hi = mid;
    }
    return lo + (t - ts[lo]) / (ts[hi] - ts[lo]);
  }

  x(t: number): number | null {
    const logical = this.logicalOf(t);
    return logical == null ? null : this.chart.timeScale().logicalToCoordinate(logical as Logical);
  }

  time(x: number): number | null {
    const ts = this.times;
    const n = ts.length;
    const logical = this.chart.timeScale().coordinateToLogical(x);
    if (logical == null || n === 0) return null;
    if (n === 1) return ts[0];
    if (logical <= 0) return Math.round(ts[0] + logical * (ts[1] - ts[0]));
    if (logical >= n - 1) return Math.round(ts[n - 1] + (logical - (n - 1)) * (ts[n - 1] - ts[n - 2]));
    const i = Math.floor(logical);
    return Math.round(ts[i] + (logical - i) * (ts[i + 1] - ts[i]));
  }
}

function distanceToSegment(p: Px, a: Px, b: Px): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = dx * dx + dy * dy;
  const t = len === 0 ? 0 : Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / len));
  return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

const price = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Draws the owner's lines on the price pane and finds which one a tap landed on. */
export class DrawingLayer implements ISeriesPrimitive<Time> {
  private drawings: Drawing[] = [];
  private preview: Drawing | null = null;
  private selectedId: string | null = null;
  private series: ISeriesApi<SeriesType> | null = null;
  private requestUpdate: (() => void) | null = null;
  private view: IPrimitivePaneView;

  constructor(private axis: TimeAxis) {
    const renderer: IPrimitivePaneRenderer = {
      draw: (target) => target.useMediaCoordinateSpace(({ context, mediaSize }) => this.draw(context, mediaSize.width)),
    };
    this.view = { renderer: () => renderer, zOrder: () => "top" };
  }

  attached({ series, requestUpdate }: SeriesAttachedParameter<Time>) {
    this.series = series;
    this.requestUpdate = requestUpdate;
  }

  detached() {
    this.series = null;
    this.requestUpdate = null;
  }

  paneViews() {
    return [this.view];
  }

  set(drawings: Drawing[], selectedId: string | null, preview: Drawing | null = this.preview) {
    this.drawings = drawings;
    this.selectedId = selectedId;
    this.preview = preview;
    this.requestUpdate?.();
  }

  setPreview(preview: Drawing | null) {
    this.preview = preview;
    this.requestUpdate?.();
  }

  private px(p: DrawingPoint): Px | null {
    const x = this.axis.x(p.time);
    const y = this.series?.priceToCoordinate(p.price);
    return x == null || y == null ? null : { x, y };
  }

  /** The drawing nearest a tap, if any is within reach. */
  hit(at: Px, width: number, reach = HIT_PX): string | null {
    let best: { id: string; d: number } | null = null;
    for (const d of this.drawings) {
      const dist = this.distance(d, at, width);
      if (dist != null && dist <= reach && (!best || dist < best.d)) best = { id: d.id, d: dist };
    }
    return best?.id ?? null;
  }

  private distance(d: Drawing, at: Px, width: number): number | null {
    const pts = d.points.map((p) => this.px(p));
    if (pts.some((p) => p == null)) return null;
    const [a, b] = pts as Px[];
    if (d.kind === "horizontal") return Math.abs(at.y - a.y);
    if (d.kind === "trend") return distanceToSegment(at, a, b);
    const left = Math.min(a.x, b.x);
    const right = d.kind === "fib" ? width : Math.max(a.x, b.x);
    const top = Math.min(a.y, b.y);
    const bottom = Math.max(a.y, b.y);
    if (at.x >= left && at.x <= right && at.y >= top && at.y <= bottom) return 0;
    const corners = [{ x: left, y: top }, { x: right, y: top }, { x: right, y: bottom }, { x: left, y: bottom }];
    return Math.min(...corners.map((c, i) => distanceToSegment(at, c, corners[(i + 1) % 4])));
  }

  private draw(ctx: CanvasRenderingContext2D, width: number) {
    for (const d of this.drawings) this.drawOne(ctx, d, width, d.id === this.selectedId);
    if (this.preview) this.drawOne(ctx, this.preview, width, true);
  }

  private drawOne(ctx: CanvasRenderingContext2D, d: Drawing, width: number, selected: boolean) {
    const pts = d.points.map((p) => this.px(p));
    if (pts.some((p) => p == null)) return;
    const [a, b] = pts as Px[];
    ctx.save();
    ctx.strokeStyle = COLOR;
    ctx.fillStyle = COLOR;
    ctx.lineWidth = selected ? 2.5 : 1.75;
    ctx.font = "500 11px system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
    ctx.textBaseline = "middle";

    if (d.kind === "trend") {
      this.line(ctx, a, b);
    } else if (d.kind === "horizontal") {
      this.line(ctx, { x: 0, y: a.y }, { x: width, y: a.y });
      this.label(ctx, price(d.points[0].price), width - 6, a.y, "right");
    } else if (d.kind === "rectangle") {
      const x = Math.min(a.x, b.x);
      const y = Math.min(a.y, b.y);
      ctx.fillStyle = FILL;
      ctx.fillRect(x, y, Math.abs(b.x - a.x), Math.abs(b.y - a.y));
      ctx.strokeRect(x, y, Math.abs(b.x - a.x), Math.abs(b.y - a.y));
    } else {
      // Retracement levels between the two prices, measured back from the second point.
      const left = Math.min(a.x, b.x);
      const [p1, p2] = [d.points[0].price, d.points[1].price];
      ctx.fillStyle = FILL;
      ctx.fillRect(left, Math.min(a.y, b.y), width - left, Math.abs(b.y - a.y));
      ctx.fillStyle = COLOR;
      ctx.lineWidth = selected ? 1.75 : 1;
      for (const r of FIB_RATIOS) {
        const level = p2 - r * (p2 - p1);
        const y = this.series?.priceToCoordinate(level);
        if (y == null) continue;
        this.line(ctx, { x: left, y }, { x: width, y });
        this.label(ctx, `${(r * 100).toFixed(1)}%  ${price(level)}`, left + 4, y - 8, "left");
      }
      ctx.setLineDash([4, 4]);
      this.line(ctx, a, b);
    }

    if (selected) {
      ctx.setLineDash([]);
      for (const p of d.kind === "horizontal" ? [a] : [a, b]) {
        ctx.beginPath();
        ctx.arc(d.kind === "horizontal" ? width / 2 : p.x, p.y, 4.5, 0, Math.PI * 2);
        ctx.fillStyle = "#ffffff";
        ctx.fill();
        ctx.lineWidth = 2;
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  private line(ctx: CanvasRenderingContext2D, a: Px, b: Px) {
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
  }

  private label(ctx: CanvasRenderingContext2D, text: string, x: number, y: number, align: "left" | "right") {
    const w = ctx.measureText(text).width + 8;
    const left = align === "right" ? x - w : x;
    ctx.save();
    ctx.fillStyle = "rgb(255 255 255 / 0.9)";
    ctx.fillRect(left, y - 8, w, 16);
    ctx.fillStyle = COLOR;
    ctx.textAlign = "left";
    ctx.fillText(text, left + 4, y);
    ctx.restore();
  }
}
