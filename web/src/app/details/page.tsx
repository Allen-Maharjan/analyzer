import { ArrowLeft } from "lucide-react";
import Link from "next/link";

import { AppShell, CardGrid, ErrorState, Section } from "@/components/AppShell";
import type { ChartLevel } from "@/components/CandleChart";
import { WorldChart } from "@/components/WorldChart";
import { DecisionLabel } from "@/components/Decision";
import { PROVIDER_NAMES, type AiOverview } from "@/lib/ai";
import { BackendError, backend, backendOrNull, type Dashboard } from "@/lib/backend";
import { withAsset, type Asset } from "@/lib/asset";
import { nepalTime, percent, rupees, usd } from "@/lib/format";

export const dynamic = "force-dynamic";

/* The snapshot detail is free-form JSON from the analysis engine; these are the parts shown here. */
type Component = { name: string; value: number | null; inputs: Record<string, unknown>; note: string | null };
type LevelState = { level_id: string; price: number; state: string; direction: string | null };
type TimeframeDetail = {
  indicators: Record<string, number | null>;
  levels: { id: string; price: number; kind: string; manual: boolean; touches: number }[];
  level_states: LevelState[];
  swing_structure: number;
  components: Record<string, Component>;
};
type Snapshot = {
  asset: Asset;
  id: string;
  created_at: string;
  decision: { decision: string; rule: string; reasons: { plain: string; detail: string }[] };
  score: {
    deterministic: number | null;
    ai_adjusted: number | null;
    ai_status: string;
    outlook: string | null;
    coverage: number;
    weights: Record<string, number>;
    components: Record<string, Component>;
  };
  prices: {
    world_usd_now: number | null;
    world_usd_source: string;
    usd_npr_mid: number | null;
    reference_per_tola_now: number | null;
    nepal_next?: { publish_at: string; estimate: number; low: number; high: number } | null;
  };
  nepal_lag: {
    latest: { nepal_price: number; reference: number; premium: number; at: string; time_known: boolean } | null;
    premium_mean: number | null;
    premium_std: number | null;
    premium_observations: number;
    implied_nepal_now: number | null;
    expected_adjustment_pct: number | null;
    adjustment_pending: boolean | null;
    intl_change_since_publication_pct: number | null;
  };
  timeframes: Record<string, TimeframeDetail>;
  versions: Record<string, string>;
};
type Signal = { key: string; name: string; value: string; signal: number; reading: string; explain: string };
type Scenario = {
  name: string;
  probability: number;
  probability_low: number;
  probability_high: number;
  count: number;
  band_usd: [number, number] | null;
  band_npr_per_tola: [number, number] | null;
  condition: string;
};
type Forecast = {
  label: string;
  status: string;
  reason?: string;
  sample_size?: number;
  first_analogue?: string;
  most_likely?: string | null;
  scenarios?: Scenario[];
  range_usd?: [number, number];
  median_usd?: number;
  invalidation?: { bearish: number; bullish: number };
};
type Extra = {
  technical?: Record<string, { signals: Signal[]; tally: { up: number; down: number; neutral: number } }>;
  price_levels?: {
    fibonacci: { high: number; low: number; direction: string; levels: { ratio: number; price: number }[] } | null;
    pivots: { based_on: string; levels: Record<string, number> } | null;
  };
  forecasts?: Forecast[];
};
type CandleSeries = { candles: { bucket_start: string; open: number; high: number; low: number; close: number }[] };

const COMPONENT_HELP: Record<string, string> = {
  trend: "Is the price generally heading up or down?",
  momentum: "Is the move speeding up or slowing down?",
  structure: "Is the price making higher or lower turning points, and has it broken key levels?",
  macro: "Are US interest rates and the dollar helping or hurting prices?",
  event_risk: "Lowers confidence close to big US announcements.",
};
const STATE_WORDS: Record<string, string> = {
  touch: "touching",
  intrabar_breach: "crossed, not yet confirmed",
  confirmed_break: "broken",
  retest: "broken, being retested",
  reclaim: "broken, then recovered",
};
const TIMEFRAMES = ["15m", "1h", "4h", "1D", "1W"];

function score(value: number | null | undefined) {
  if (value == null) return <span className="text-ink-2">no data</span>;
  const tone = value > 20 ? "text-buy" : value < -20 ? "text-wait" : "text-ink";
  return <span className={`num font-medium ${tone}`}>{value > 0 ? "+" : value < 0 ? "−" : ""}{Math.abs(value).toFixed(0)}</span>;
}

export default async function DetailsPage({ searchParams }: { searchParams: Promise<{ id?: string; asset?: string }>  }) {
  const { id, asset = "gold" } = await searchParams;
  let snapshot: Snapshot | null = null;
  let candles: CandleSeries | null = null;
  const ai = await backend<AiOverview>(withAsset("/api/v1/ai", asset)).catch(() => null);
  try {
    const snapshotId = id && /^[0-9a-f-]{36}$/.test(id) ? id : (await backendOrNull<Dashboard>(withAsset("/api/v1/dashboard", asset)))?.snapshot_id;
    if (snapshotId) {
      [snapshot, candles] = await Promise.all([
        backendOrNull<Snapshot>(withAsset(`/api/v1/snapshots/${snapshotId}`, asset)),
        backend<CandleSeries>(withAsset("/api/v1/candles?timeframe=15m&limit=192", asset)),
      ]);
    }
  } catch (error) {
    return (
      <AppShell asset={asset}>
        <ErrorState message={error instanceof BackendError ? error.message : "Something went wrong."} />
      </AppShell>
    );
  }
  if (!snapshot) {
    return (
      <AppShell asset={asset}>
        <h1 className="text-2xl font-semibold">No analysis yet</h1>
        <p className="mt-2 text-ink-2">Details appear after the first analysis has run.</p>
      </AppShell>
    );
  }

  const s = snapshot as Snapshot & Extra;
  const lag = s.nepal_lag;
  const daily = s.timeframes["1D"];
  const close = s.prices.world_usd_now ?? 0;
  // For each chart timeframe: the two nearest support levels below the price and the two nearest
  // resistance levels above it, from that timeframe's own analysis, plus the owner's watch levels.
  const watchLevels: ChartLevel[] = (daily?.levels ?? []).filter((l) => l.manual).map((l) => ({ ...l, kind: "watch" }));
  const chartLevels = Object.fromEntries(
    (["15m", "1h", "1D"] as const).map((tf) => {
      const found = (s.timeframes[tf]?.levels ?? []).filter((l) => !l.manual);
      const supports = found.filter((l) => l.price < close).sort((a, b) => b.price - a.price).slice(0, 2);
      const resistances = found.filter((l) => l.price > close).sort((a, b) => a.price - b.price).slice(0, 2);
      return [tf, [
        ...supports.map((l): ChartLevel => ({ ...l, kind: "support" })),
        ...resistances.map((l): ChartLevel => ({ ...l, kind: "resistance" })),
        ...watchLevels,
      ]];
    }),
  ) as Record<"15m" | "1h" | "1D", ChartLevel[]>;

  const rows = (items: [string, React.ReactNode][]) => (
    <dl className="divide-y divide-line text-[15px]">
      {items.map(([label, value]) => (
        <div key={label} className="flex justify-between gap-4 py-2.5">
          <dt className="text-ink-2">{label}</dt>
          <dd className="num text-right">{value}</dd>
        </div>
      ))}
    </dl>
  );

  return (
    <AppShell asset={asset}>
      <Link href={withAsset("/", asset)} className="-ml-1 inline-flex min-h-11 items-center gap-1 text-[15px] text-ink-2 hover:text-ink">
        <ArrowLeft aria-hidden className="size-4" strokeWidth={1.75} /> Today
      </Link>
      <h1 className="mt-1 text-[1.75rem] font-semibold leading-tight tracking-tight">Detailed analysis</h1>
      <p className="mt-2 text-sm text-ink-2">
        <DecisionLabel decision={s.decision.decision} /> · {nepalTime(s.created_at)}
      </p>

      <CardGrid>
      <Section title="Nepal vs world price" updated={s.created_at}>
        <p className="mb-3 text-sm leading-relaxed text-ink-2">
          World {snapshot.asset.label.toLowerCase()} converted to rupees per tola (price × dollar rate × 0.375). Nepal's price normally sits a steady
          amount above it because of duty and dealer costs. Nepal follows the world price of about 9:45 am; the next update is estimated by
          carrying today&apos;s gap forward to the latest world price and dollar rate.
        </p>
        {rows([
          ["Nepal price", rupees(lag.latest?.nepal_price)],
          ["World price in rupees", rupees(s.prices.reference_per_tola_now)],
          ["Dollar rate (NRB)", s.prices.usd_npr_mid != null ? `Rs ${s.prices.usd_npr_mid.toFixed(2)}` : "—"],
          ["Usual gap", lag.premium_mean != null ? percent(lag.premium_mean) : "not enough history"],
          ["Gap today", percent(lag.latest?.premium)],
          [
            "Expected at next update",
            s.prices.nepal_next ? (
              <>
                {rupees(s.prices.nepal_next.estimate)}
                <span className="block text-xs text-ink-2">
                  likely {rupees(s.prices.nepal_next.low)}–{rupees(s.prices.nepal_next.high)} · {nepalTime(s.prices.nepal_next.publish_at)}
                </span>
              </>
            ) : lag.implied_nepal_now != null ? rupees(lag.implied_nepal_now) : "—",
          ],
          [`World ${snapshot.asset.label.toLowerCase()} since Nepal's update`, percent(lag.intl_change_since_publication_pct)],
        ])}
      </Section>

      <Section title={`World ${snapshot.asset.label.toLowerCase()} prices`}>
        <WorldChart key={asset} asset={asset} label={snapshot.asset.label.toLowerCase()} initialCandles={candles?.candles ?? []} levels={chartLevels} />
      </Section>

      <Section title="AI analysis" updated={ai?.result?.finished_at}>
        {ai?.result ? (
          <>
            <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1">
              <p className="text-sm text-ink-2">
                Outlook <span className="font-medium capitalize text-ink">{ai.result.output.outlook}</span>
              </p>
              <p className="text-sm text-ink-2">
                Score {score(ai.result.deterministic_score)} → {score(ai.result.adjusted_score)}{" "}
                <span className="num">({ai.result.output.adjustment > 0 ? "+" : ""}{ai.result.output.adjustment})</span>
              </p>
            </div>
            <p className="mt-2 text-sm text-ink-2">{ai.result.output.adjustment_reason}</p>
            <ul className="mt-4 divide-y divide-line">
              {ai.result.output.reasons.map((r) => (
                <li key={r.text} className="py-2.5">
                  <p className="text-[15px] leading-relaxed">{r.text}</p>
                  <p className="num mt-0.5 text-xs text-ink-2">Evidence: {r.evidence_ids.join(", ")}</p>
                </li>
              ))}
            </ul>
            {ai.result.output.risks.length > 0 && (
              <>
                <h3 className="mt-4 text-sm font-semibold">What could make this wrong</h3>
                <ul className="mt-1 space-y-1 text-[15px] text-ink-2">
                  {ai.result.output.risks.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </>
            )}
            {ai.result.output.watch_levels.length > 0 && (
              <p className="num mt-3 text-sm text-ink-2">Levels to watch: {ai.result.output.watch_levels.join(", ")}</p>
            )}
            <p className="mt-4 text-xs text-ink-2">
              {PROVIDER_NAMES[ai.result.provider] ?? ai.result.provider}
              {ai.result.model ? ` (${ai.result.model})` : ""} · {ai.result.cli_version} · {nepalTime(ai.result.finished_at)}.
              The AI can move the score by at most 5 points and cannot change the decision. Every price it quotes is
              checked against the app's numbers.
            </p>
          </>
        ) : (
          <p className="text-ink-2">No AI answer yet. Ask from the Today page.</p>
        )}
      </Section>

      {s.forecasts && s.forecasts.length > 0 && (
        <Section title="Scenarios" updated={s.created_at}>
          <p className="mb-3 text-sm leading-relaxed text-ink-2">
            For each time span, the app finds up to 100 past days most like today (trend, momentum, RSI, recent move,
            volatility) and counts what happened next. Ranges are the 10th to 90th percentile of those outcomes.
          </p>
          <ul className="space-y-6">
            {s.forecasts.map((f) => (
              <li key={f.label}>
                <p className="font-medium">
                  Next {f.label}
                  {f.status === "ok" && (
                    <span className="num font-normal text-ink-2">
                      {" "}· {f.sample_size} similar days · middle outcome {usd(f.median_usd)}
                    </span>
                  )}
                </p>
                {f.status !== "ok" ? (
                  <p className="mt-1 text-sm text-ink-2">{f.reason}</p>
                ) : (
                  <ul className="mt-2 divide-y divide-line text-[15px]">
                    {(f.scenarios ?? []).map((sc) => (
                      <li key={sc.name} className="flex items-baseline justify-between gap-3 py-2">
                        <span>
                          <span
                            className={`font-medium capitalize ${sc.name === "bearish" ? "text-wait" : sc.name === "bullish" ? "text-buy" : ""}`}
                          >
                            {sc.name}
                          </span>
                          <span className="block text-xs text-ink-2">{sc.condition}</span>
                        </span>
                        <span className="num text-right">
                          {Math.round(sc.probability * 100)}%
                          <span className="block text-xs text-ink-2">
                            {Math.round(sc.probability_low * 100)}–{Math.round(sc.probability_high * 100)}% ·{" "}
                            {sc.band_usd ? `${usd(sc.band_usd[0])}–${usd(sc.band_usd[1])}` : "too few cases"}
                          </span>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Reasons" updated={s.created_at}>
        <ul className="space-y-5">
          {s.decision.reasons.map((r) => (
            <li key={r.plain}>
              <p className="text-[17px] leading-relaxed">{r.plain}</p>
              <p className="num mt-1 text-sm text-ink-2">{r.detail}</p>
            </li>
          ))}
        </ul>
      </Section>

      {s.technical && (
        <Section title="Indicators" updated={s.created_at}>
          <div className="mb-4 grid grid-cols-4 gap-2 text-center text-xs">
            {["1h", "4h", "1D", "1W"].filter((tf) => s.technical?.[tf]).map((tf) => {
              const t = s.technical![tf].tally;
              return (
                <div key={tf} className="rounded-lg bg-ground px-2 py-2">
                  <p className="font-semibold text-ink">{tf}</p>
                  <p className="num mt-0.5">
                    <span className="text-buy">{t.up}↑</span> <span className="text-wait">{t.down}↓</span>
                  </p>
                </div>
              );
            })}
          </div>
          <p className="mb-2 text-sm text-ink-2">Daily readings. ↑ points to rising prices, ↓ to falling.</p>
          <ul className="divide-y divide-line">
            {(s.technical["1D"]?.signals ?? []).map((sig) => (
              <li key={sig.key} className="py-3">
                <div className="flex items-baseline justify-between gap-3 text-[15px]">
                  <span className="flex items-center gap-2 font-medium">
                    <span
                      aria-hidden
                      className={`size-2 rounded-full ${sig.signal > 0 ? "bg-buy" : sig.signal < 0 ? "bg-wait" : "bg-ink-2/40"}`}
                    />
                    {sig.name}
                  </span>
                  <span className="num text-right text-ink-2">{sig.value}</span>
                </div>
                <p className="mt-1 text-[15px] leading-relaxed">{sig.reading}</p>
                <p className="mt-0.5 text-xs text-ink-2">{sig.explain}</p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {s.price_levels && (s.price_levels.pivots || s.price_levels.fibonacci) && (
        <Section title="Price levels" updated={s.created_at}>
          {s.price_levels.pivots && (
            <>
              <p className="text-sm text-ink-2">
                Pivot points from the last full trading day. Traders watch these as likely turning prices: R above the
                price, S below.
              </p>
              <dl className="num mt-3 grid grid-cols-7 gap-1 text-center text-xs">
                {Object.entries(s.price_levels.pivots.levels).map(([k, v]) => (
                  <div key={k} className={`rounded-md py-2 ${k === "P" ? "bg-accent-soft" : "bg-ground"}`}>
                    <dt className={`font-semibold ${k.startsWith("R") ? "text-wait" : k.startsWith("S") ? "text-buy" : "text-accent-hover"}`}>{k}</dt>
                    <dd className="mt-0.5 text-ink">{Math.round(v)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
          {s.price_levels.fibonacci && (
            <>
              <p className="mt-5 text-sm text-ink-2">
                Fibonacci levels across the last six months ({usd(s.price_levels.fibonacci.high)} to{" "}
                {usd(s.price_levels.fibonacci.low)}, moving {s.price_levels.fibonacci.direction}). Bounces often stall
                near 38.2%, 50% and 61.8%.
              </p>
              <ul className="num mt-2 divide-y divide-line text-[15px]">
                {s.price_levels.fibonacci.levels.map((l) => {
                  const near = close && Math.abs(l.price - close) / close < 0.01;
                  return (
                    <li key={l.ratio} className={`flex justify-between py-1.5 ${near ? "font-semibold text-accent-hover" : ""}`}>
                      <span>{(l.ratio * 100).toFixed(1)}%</span>
                      <span>
                        {usd(l.price)}
                        {near ? " · near now" : ""}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </Section>
      )}

      <Section title="Market score" updated={s.created_at}>
        <p className="text-4xl">{score(s.score.deterministic)}</p>
        <p className="mt-1 text-sm text-ink-2">
          From −100 (falling hard) to +100 (rising hard) · {s.score.outlook ?? "unknown"} · {Math.round(s.score.coverage * 100)}% of data available
        </p>
        <ul className="mt-5 divide-y divide-line">
          {Object.entries(s.score.weights).map(([name, weight]) => {
            const c = s.score.components[name];
            return (
              <li key={name} className="py-3">
                <div className="flex justify-between gap-4 text-[15px]">
                  <span className="font-medium capitalize">{name.replace("_", " ")}</span>
                  <span>
                    {score(c?.value)} <span className="num text-ink-2">· {Math.round(weight * 100)}%</span>
                  </span>
                </div>
                <p className="mt-0.5 text-sm text-ink-2">{COMPONENT_HELP[name]}</p>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section title="By time scale" updated={s.created_at}>
        <ul className="divide-y divide-line">
          {TIMEFRAMES.filter((tf) => s.timeframes[tf]).map((tf) => {
            const t = s.timeframes[tf];
            return (
              <li key={tf} className="py-3 text-[15px]">
                <div className="flex justify-between gap-4">
                  <span className="font-medium">{tf}</span>
                  <span className="num text-ink-2">
                    trend {score(t.components.trend?.value)} · momentum {score(t.components.momentum?.value)} · RSI{" "}
                    {t.indicators.rsi_14?.toFixed(0) ?? "—"}
                  </span>
                </div>
                {t.level_states.length > 0 && (
                  <p className="num mt-1 text-sm text-ink-2">
                    {t.level_states
                      .map((ls) => `${usd(ls.price)} ${STATE_WORDS[ls.state] ?? ls.state}`)
                      .join(" · ")}
                  </p>
                )}
              </li>
            );
          })}
        </ul>
        <p className="mt-3 text-sm text-ink-2">RSI above 70 means recently very strong, below 30 very weak.</p>
      </Section>

      </CardGrid>

      <p className="mt-12 text-xs text-ink-2">
        {Object.entries(s.versions).map(([k, v]) => `${k} ${v}`).join(" · ")}
      </p>
    </AppShell>
  );
}
