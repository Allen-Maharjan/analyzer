import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { AppShell, ErrorState, Section } from "@/components/AppShell";
import { DecisionLabel, decisionStyle } from "@/components/Decision";
import { NepalPriceChart } from "@/components/NepalPriceChart";
import { PlanActions } from "@/components/PlanActions";
import { ScenarioBar } from "@/components/ScenarioBar";
import { AskAiButton } from "@/components/AskAiButton";
import { PROVIDER_NAMES, type AiOverview } from "@/lib/ai";
import { BackendError, backend, backendOrNull, type Dashboard } from "@/lib/backend";
import { withAsset } from "@/lib/asset";
import { ago, nepalDate, nepalTime, rupees } from "@/lib/format";

export const dynamic = "force-dynamic";

const CONFIDENCE_WORDS: Record<string, string> = { high: "Fairly sure", medium: "Somewhat sure", low: "Not very sure" };
const STATUS_WORDS: Record<string, string> = {
  fresh: "up to date",
  market_closed: "market closed",
  stale: "out of date",
  unavailable: "not available",
};

type Plan = { waiting_since: string | null; completed_at: string | null };

export default async function TodayPage({ searchParams }: { searchParams: Promise<{ asset?: string }> }) {
  const { asset = "gold" } = await searchParams;
  let dashboard: Dashboard | null;
  let plan: Plan;
  let ai: AiOverview | null;
  try {
    [dashboard, plan, ai] = await Promise.all([
      backendOrNull<Dashboard>(withAsset("/api/v1/dashboard", asset)),
      backend<Plan>(withAsset("/api/v1/plan", asset)),
      backend<AiOverview>(withAsset("/api/v1/ai", asset)).catch(() => null),
    ]);
  } catch (error) {
    return (
      <AppShell asset={asset}>
        <ErrorState message={error instanceof BackendError ? error.message : "Something went wrong."} />
      </AppShell>
    );
  }

  if (!dashboard) {
    return (
      <AppShell asset={asset}>
        <h1 className="text-2xl font-semibold">No advice yet</h1>
        <p className="mt-2 text-ink-2">
          The app is collecting its first prices. Advice appears a few minutes after setup.
        </p>
      </AppShell>
    );
  }

  const d = dashboard;
  const label = d.asset.label.toLowerCase();
  const tone = decisionStyle(d.decision);
  const stripped = d.headline.replace(/^(Wait|Hold off|Keep watching)\s*:\s*/i, "");
  const headline = stripped.charAt(0).toUpperCase() + stripped.slice(1);
  const WORDS: Record<string, string> = { bearish: "lower", neutral: "about the same", bullish: "higher" };
  const history = d.prices.nepal_history;
  const previous = history.length >= 2 ? history[history.length - 2].price : null;
  const change = previous != null && d.prices.nepal_per_tola != null ? d.prices.nepal_per_tola - previous : null;
  const sourceNames = Object.fromEntries(d.sources.map(s => [s.dataset, s.dataset === "usd_npr" ? "Dollar rate" : s.dataset.startsWith("nepal_") ? `Nepal ${label}` : s.dataset.endsWith("_spot") ? `World ${label}` : s.dataset]));
  const sources = d.sources.filter(s => s.dataset === "usd_npr" || s.dataset.startsWith("nepal_") || s.dataset.endsWith("_spot"));
  const problems = sources.filter((s) => s.status === "stale" || s.status === "unavailable");

  return (
    <AppShell asset={asset}>
      <section aria-labelledby="advice" className={`rounded-2xl border ${tone.ring} ${tone.soft} p-5 sm:p-6`}>
        <DecisionLabel decision={d.decision} className="rounded-full bg-panel/70 px-3 py-1 text-sm uppercase tracking-wide" />
        <h1 id="advice" className="mt-3 text-[1.75rem] font-semibold leading-tight tracking-tight text-ink">
          {headline}
        </h1>
        <p className="mt-3 max-w-[55ch] text-lg leading-relaxed text-ink">{d.summary}</p>
        <p className="mt-4 text-sm text-ink-2">
          {CONFIDENCE_WORDS[d.confidence] ?? d.confidence} · Check again {d.next_review.charAt(0).toLowerCase() + d.next_review.slice(1)}
        </p>
      </section>

      {d.waiting.review_due && (
        <p className="mt-4 rounded-2xl border border-watch/20 bg-watch-soft p-4 text-[15px]">
          <span className="font-semibold">You've waited {Math.floor(d.waiting.days ?? 0)} days.</span> Only keep waiting if the
          reasons below still make sense today.
        </p>
      )}

      <Section title={`Nepal ${label}, per tola`}>
        {d.prices.nepal_per_tola == null ? (
          <p className="text-ink-2">Not collected yet.</p>
        ) : (
          <>
            <p className="num text-4xl font-semibold tracking-tight">{rupees(d.prices.nepal_per_tola)}</p>
            <p className="mt-1 text-sm text-ink-2">
              {d.asset.local_label} ·{" "}
              {d.prices.nepal_time_known && d.prices.nepal_published_at
                ? nepalTime(d.prices.nepal_published_at)
                : nepalDate(d.prices.nepal_date)}
              {change != null && change !== 0 && (
                <span className={`num font-medium ${change > 0 ? "text-wait" : "text-buy"}`}> · {change > 0 ? "up" : "down"} {rupees(Math.abs(change))} since last update</span>
              )}
            </p>
            <div className="mt-5">
              <NepalPriceChart points={history} />
            </div>
          </>
        )}
      </Section>

      <Section title="AI's take">
        {ai?.result ? (
          <>
            <p className="text-[17px] leading-relaxed">{ai.result.output.plain_summary}</p>
            <p className="mt-2 text-xs text-ink-2">
              {PROVIDER_NAMES[ai.result.provider] ?? ai.result.provider} · {ago(ai.result.finished_at)} · checked against the
              app's own numbers
            </p>
          </>
        ) : (
          <p className="text-ink-2">No AI answer yet.</p>
        )}
        {ai?.latest_run && ["failed", "invalid", "expired"].includes(ai.latest_run.status) && (
          <p className="mt-2 text-sm text-ink-2">
            The last AI check didn't work{ai.latest_run.status === "invalid" ? " (its answer quoted numbers the app couldn't confirm, so it was not used)" : ""}.
            {ai.result ? " Showing the previous answer." : ""}
          </p>
        )}
        <div className="mt-4">
          <AskAiButton key={asset} asset={asset} busy={!!ai?.latest_run && ["queued", "running"].includes(ai.latest_run.status)} />
        </div>
      </Section>

      {d.forecasts.length > 0 && (
        <Section title={`What might happen to world ${label}`}>
          <ul className="space-y-5">
            {d.forecasts.map((f) => (
              <li key={f.label}>
                <div className="mb-2 flex items-baseline justify-between gap-3">
                  <span className="font-medium">Next {f.label}</span>
                  <span className="text-sm text-ink-2">
                    {f.status !== "ok" ? "not enough data" : f.most_likely ? `Most likely ${WORDS[f.most_likely]}` : "No clear direction"}
                  </span>
                </div>
                {f.status === "ok" ? (
                  <>
                    <ScenarioBar p={f.probabilities} />
                    {f.range_npr_per_tola?.[0] != null && f.range_npr_per_tola?.[1] != null && (
                      <p className="num mt-1.5 text-sm text-ink-2">
                        Nepal price would usually land between {rupees(f.range_npr_per_tola[0])} and{" "}
                        {rupees(f.range_npr_per_tola[1])}
                      </p>
                    )}
                  </>
                ) : (
                  <p className="text-sm text-ink-2">{f.reason}</p>
                )}
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs leading-relaxed text-ink-2">
            Based on what happened after the {d.forecasts[0]?.sample_size ?? 100} most similar days in the available history. A guide, not a promise.
          </p>
        </Section>
      )}

      <Section title="Why">
        <ul className="space-y-3 text-[17px] leading-relaxed">
          {d.reasons.map((reason) => (
            <li key={reason.plain} className="flex gap-3">
              <span aria-hidden className="mt-2.5 size-1.5 shrink-0 rounded-full bg-accent" />
              <span>{reason.plain}</span>
            </li>
          ))}
        </ul>
        <Link
          href={withAsset(`/details?id=${d.snapshot_id}`, asset)}
          className="mt-5 inline-flex min-h-11 items-center gap-1.5 rounded-xl bg-accent px-4 text-[15px] font-semibold text-white transition-colors hover:bg-accent-hover"
        >
          View detailed analysis
          <ArrowRight aria-hidden className="size-4" strokeWidth={1.75} />
        </Link>
      </Section>

      <Section title="What would change this">
        <p className="text-[17px] leading-relaxed">{d.what_would_change}</p>
        {d.next_event && (
          <p className="mt-3 text-[15px] text-ink-2">
            Next big US announcement: {d.next_event.title.replace(/\s*\(.*\)$/, "")}, {nepalTime(d.next_event.scheduled_at)}.
          </p>
        )}
      </Section>

      <Section title="Your purchase">
        <p className="mb-3 text-[15px] text-ink-2">
          {plan.completed_at
            ? `Bought on ${nepalTime(plan.completed_at)}.`
            : plan.waiting_since
              ? `Waiting ${Math.floor(d.waiting.days ?? 0)} of 7 days.`
              : "Not waiting yet."}
        </p>
        <PlanActions key={asset} plan={plan} asset={asset} label={label} />
      </Section>

      <footer className="mt-6 px-1 text-xs leading-relaxed text-ink-2">
        <p>Advice updated {ago(d.created_at)}.</p>
        <p className={problems.length ? "font-medium text-ink" : ""}>
          {sources
            .map((s) => `${sourceNames[s.dataset]} ${STATUS_WORDS[s.status] ?? s.status}`)
            .join(" · ")}
        </p>
      </footer>
    </AppShell>
  );
}
