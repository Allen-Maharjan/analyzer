import { CircleCheck, CircleX } from "lucide-react";

import { AppShell, ErrorState, Section } from "@/components/AppShell";
import { DecisionLabel } from "@/components/Decision";
import type { components } from "@/lib/api-types";
import { withAsset } from "@/lib/asset";
import { BackendError, backend } from "@/lib/backend";
import { nepalDate, nepalTime, rupees } from "@/lib/format";

export const dynamic = "force-dynamic";

type TrackRecord = components["schemas"]["TrackRecordOut"];
type ForecastSummary = components["schemas"]["TrackForecastSummaryOut"];
type AdviceSummary = components["schemas"]["TrackAdviceSummaryOut"];

function forecastSentence(s: ForecastSummary, label: string): string {
  if (!s.count || s.mean_abs_error_npr == null) return "";
  const updates = s.count === 1 ? "the last price update" : `the last ${s.count} price updates`;
  return (
    `Over ${updates}, the app's guess for the next Nepal ${label} price was off by ${rupees(s.mean_abs_error_npr)} on average. ` +
    `${s.inside_range} of the ${s.count} landed inside the range it gave.`
  );
}

function adviceSentence(s: AdviceSummary): string {
  if (s.status !== "ok" || s.mean_cost_vs_immediate == null) {
    return `Too early to judge the advice as a whole: ${s.windows} of ${s.windows_needed} weeks collected.`;
  }
  const pct = Math.abs(s.mean_cost_vs_immediate * 100).toFixed(2);
  const word = s.mean_cost_vs_immediate <= 0 ? "less" : "more";
  return `Across ${s.windows} weeks, following the advice paid on average ${pct}% ${word} than buying on the first day of each week.`;
}

function Mark({ good, children }: { good: boolean; children: React.ReactNode }) {
  const Icon = good ? CircleCheck : CircleX;
  return (
    <span className={`inline-flex items-center gap-1 font-medium ${good ? "text-buy" : "text-wait"}`}>
      <Icon aria-hidden className="size-4 shrink-0" strokeWidth={2} />
      {children}
    </span>
  );
}

function difference(error: number): string {
  if (error === 0) return "exactly as guessed";
  return `${rupees(Math.abs(error))} ${error > 0 ? "higher" : "lower"} than guessed`;
}

export default async function TrackRecordPage({ searchParams }: { searchParams: Promise<{ asset?: string }> }) {
  const { asset = "gold" } = await searchParams;
  let data: TrackRecord;
  try {
    data = await backend<TrackRecord>(withAsset("/api/v1/track-record?limit=60", asset));
  } catch (error) {
    return (
      <AppShell asset={asset}>
        <ErrorState message={error instanceof BackendError ? error.message : "Something went wrong."} />
      </AppShell>
    );
  }
  const label = data.asset.label.toLowerCase();
  const { forecast, advice } = data;

  if (!forecast.rows.length && !advice.rows.length) {
    return (
      <AppShell asset={asset}>
        <h1 className="text-2xl font-semibold tracking-tight">Track record</h1>
        <p className="mt-2 max-w-[55ch] text-ink-2">
          Nothing to check yet. Once the app has made a guess before one of Nepal&apos;s price updates, the guess and the real price appear
          here side by side.
        </p>
      </AppShell>
    );
  }

  return (
    <AppShell asset={asset}>
      <h1 className="text-2xl font-semibold tracking-tight">Track record</h1>
      <p className="mt-1 text-sm text-ink-2">The app&apos;s past guesses and advice for {label}, checked against the prices Nepal really published.</p>

      <div className="mt-4 rounded-2xl border border-line bg-panel p-5">
        {forecast.summary.count > 0 && (
          <p className="text-[17px] leading-relaxed">
            {forecastSentence(forecast.summary, label)}
            {forecast.summary.small_sample && (
              <span className="ml-2 whitespace-nowrap rounded-full bg-watch-soft px-2 py-0.5 align-middle text-xs font-medium text-ink">
                Small sample: {forecast.summary.count} {forecast.summary.count === 1 ? "day" : "days"}
              </span>
            )}
          </p>
        )}
        <p className={`text-[17px] leading-relaxed ${forecast.summary.count > 0 ? "mt-3" : ""}`}>{adviceSentence(advice.summary)}</p>
      </div>

      <Section title="Guesses for Nepal's next price">
        {forecast.rows.length === 0 ? (
          <p className="text-ink-2">No guesses to check yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {forecast.rows.map((r) => (
              <li key={r.rate_date} className="py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-medium">{nepalDate(r.rate_date)}</span>
                  <Mark good={r.inside_range}>{r.inside_range ? "inside the range" : "outside the range"}</Mark>
                </div>
                <p className="num mt-1 text-[15px]">
                  Guessed {rupees(r.estimate)} · Actual {rupees(r.actual)}
                </p>
                <p className="num text-sm text-ink-2">
                  {difference(r.error_npr)} · range {rupees(r.low)} to {rupees(r.high)} · guessed {r.hours_before} h before
                </p>
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Advice at noon on each price day">
        {advice.rows.length === 0 ? (
          <p className="text-ink-2">No advice to check yet.</p>
        ) : (
          <ul className="divide-y divide-line">
            {advice.rows.map((r) => (
              <li key={r.rate_date} className="py-3 first:pt-0 last:pb-0">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                  <span className="font-medium">{nepalDate(r.rate_date)}</span>
                  <DecisionLabel decision={r.decision} className="text-sm" />
                </div>
                <p className="num mt-1 text-[15px]">Price that day {rupees(r.price)}</p>
                <p className="text-sm">
                  {r.good == null ? (
                    <span className="text-ink-2">{r.open ? `Still open: ${r.later_count} of 5 later updates so far` : r.outcome}</span>
                  ) : (
                    <Mark good={r.good}>{r.outcome.charAt(0).toUpperCase() + r.outcome.slice(1)}</Mark>
                  )}
                </p>
                <p className="num text-xs text-ink-2">Advice from {nepalTime(r.advice_at)}</p>
              </li>
            ))}
          </ul>
        )}
        <p className="mt-4 text-xs leading-relaxed text-ink-2">
          Each day shows what the rules said at 12:00 Nepal time, without any news story you flagged. The result reads only the next 5 price
          updates. Fees and making charges are not included.
        </p>
      </Section>
    </AppShell>
  );
}
