import { AlertTriangle } from "lucide-react";
import Link from "next/link";

import { AppShell, ErrorState, Section } from "@/components/AppShell";
import { TradeLog, TradeSettingsForm } from "@/components/TradeForms";
import type { components } from "@/lib/api-types";
import { TRADABLE_ASSETS, withAsset } from "@/lib/asset";
import { BackendError, backend } from "@/lib/backend";
import { longDate, nepalDate, rupees, stamp } from "@/lib/format";

export const dynamic = "force-dynamic";

type Trade = components["schemas"]["TradeOut"];
type ReplayRow = components["schemas"]["TradeReplayRowOut"];

/** The replay row for the owner's gap: the nearest tested gap at or above it (2% until it is entered). */
function replayFor(rows: ReplayRow[], gapPct: number | null): ReplayRow | undefined {
  const wanted = gapPct ?? 2;
  return [...rows].sort((a, b) => a.gap_pct - b.gap_pct).find((r) => r.gap_pct >= wanted - 1e-9) ?? rows[rows.length - 1];
}

function signed(value: number): string {
  return `${value < 0 ? "lost" : "made"} ${rupees(Math.abs(value))}`;
}

function verdict(t: Trade): { warn: boolean; text: string } {
  const rows = t.replay?.results ?? [];
  const row = replayFor(rows, t.gap_pct);
  if (!row) return { warn: true, text: "The two-year test of this plan hasn't run yet, so there is no evidence it works." };
  const gapWords = t.gap_pct == null ? `a ${row.gap_pct}% buy-back gap` : `a buy-back gap like your shop's (${row.gap_pct}% tested)`;
  const budget = rupees(t.replay?.budget_npr ?? t.budget_npr);
  if (row.total_npr < 0) {
    return {
      warn: true,
      text: `Over the past two years this plan lost money once the shop's buy-back gap is counted: it ${signed(row.total_npr)} on ${budget} at ${gapWords}, over ${row.trades} trades.`,
    };
  }
  return {
    warn: false,
    text: `Over the past two years this plan ${signed(row.total_npr)} on ${budget} at ${gapWords}, over ${row.trades} trades (${row.winning} made money).`,
  };
}

export default async function TradePage({ searchParams }: { searchParams: Promise<{ asset?: string }> }) {
  const { asset = "silver" } = await searchParams;
  if (!TRADABLE_ASSETS.has(asset)) {
    return (
      <AppShell asset={asset}>
        <h1 className="text-2xl font-semibold tracking-tight">Trade</h1>
        <p className="mt-2 max-w-[55ch] text-ink-2">
          The Trade screen is for silver only. Gold is bought for festivals, so the app never gives advice to sell it.
        </p>
        <Link href="/trade?asset=silver" className="mt-4 inline-flex min-h-11 items-center text-[15px] font-medium text-accent-hover underline">
          Open the silver Trade screen
        </Link>
      </AppShell>
    );
  }
  let t: Trade;
  try {
    t = await backend<Trade>(withAsset("/api/v1/trade", asset));
  } catch (error) {
    return (
      <AppShell asset={asset}>
        <ErrorState message={error instanceof BackendError ? error.message : "Something went wrong."} />
      </AppShell>
    );
  }
  const v = verdict(t);
  const gapKnown = t.gap_pct != null;
  const pos = t.position;

  return (
    <AppShell asset={asset}>
      <h1 className="text-2xl font-semibold tracking-tight">Silver trade plan</h1>
      <p
        className={`mt-3 flex gap-2 rounded-2xl border p-4 text-[17px] leading-relaxed ${v.warn ? "border-wait/20 bg-wait-soft" : "border-line bg-panel"}`}
      >
        {v.warn && <AlertTriangle aria-hidden className="mt-1 size-5 shrink-0 text-wait" strokeWidth={2} />}
        <span>{v.text}</span>
      </p>
      {!t.approved && (
        <p className="mt-3 rounded-2xl border border-watch/20 bg-watch-soft p-4 text-[15px]">
          <span className="font-semibold">Trial only.</span> This plan is not advice yet. It becomes advice only after you approve the test
          results above. The app never places orders; it only records what you tell it.
        </p>
      )}

      <Section title="The plan today" updated={t.snapshot_created_at}>
        {t.state == null ? (
          <p className="text-ink-2">No plan yet: the next update works it out.</p>
        ) : (
          <>
            <p className="text-[1.375rem] font-semibold leading-snug">{t.plain}</p>
            {t.nepal_price != null && (
              <p className="num mt-1 text-sm text-ink-2">
                Nepal silver {rupees(t.nepal_price)} per tola · {nepalDate(t.nepal_date)}
              </p>
            )}
            {pos.quantity_tola <= 0 && (t.second_npr != null || t.cut_npr != null) && (
              <p className="mt-4 text-sm font-medium text-ink-2">If you buy the first half now:</p>
            )}
            <ul className={`num space-y-2 text-[17px] ${pos.quantity_tola <= 0 ? "mt-2" : "mt-4"}`}>
              {t.half_quantity_tola != null && (
                <li>
                  Half your budget ({rupees(t.budget_npr / 2)}) buys about <span className="font-semibold">{t.half_quantity_tola} tola</span>.
                </li>
              )}
              {t.second_npr != null && pos.parts < 2 && (
                <li>Second half: on a day silver closes above about <span className="font-semibold">{rupees(t.second_npr)}</span>.</li>
              )}
              {t.target_npr != null && <li>Take profit at about <span className="font-semibold">{rupees(t.target_npr)}</span>.</li>}
              {t.cut_npr != null && <li>Cut the loss if a day closes below about <span className="font-semibold">{rupees(t.cut_npr)}</span>.</li>}
            </ul>
            {gapKnown ? (
              <div className="num mt-4 grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl border border-line bg-inset px-3 py-2">
                  <p className="text-ink-2">At the target, after the gap</p>
                  <p className={`mt-0.5 font-semibold ${t.profit_at_target_npr != null && t.profit_at_target_npr < 0 ? "text-wait" : "text-buy"}`}>
                    {t.profit_at_target_npr == null ? "—" : `${t.profit_at_target_npr < 0 ? "loss" : "profit"} ${rupees(Math.abs(t.profit_at_target_npr))}`}
                  </p>
                </div>
                <div className="rounded-xl border border-line bg-inset px-3 py-2">
                  <p className="text-ink-2">At the cut-loss, after the gap</p>
                  <p className="mt-0.5 font-semibold text-wait">
                    {t.loss_at_cut_npr == null ? "—" : `${t.loss_at_cut_npr < 0 ? "loss" : "profit"} ${rupees(Math.abs(t.loss_at_cut_npr))}`}
                  </p>
                </div>
              </div>
            ) : (
              <p className="mt-4 rounded-xl border border-line bg-inset p-3 text-[15px]">
                Enter your shop&apos;s buy-back gap below to see profit and loss. Until then the app shows prices only.
              </p>
            )}
            <p className="mt-3 text-xs leading-relaxed text-ink-2">
              Rupee levels are world prices turned into Nepal rupees per tola, so they are approximate. The plan is checked every 30 minutes.
            </p>
          </>
        )}
      </Section>

      <Section title="What you hold">
        {pos.quantity_tola > 0 ? (
          <ul className="num space-y-1 text-[17px]">
            <li>
              {pos.quantity_tola} tola, average {rupees(pos.average_price_npr)} ({rupees(pos.cost_npr)} paid)
            </li>
            {pos.value_after_gap_npr != null && pos.unrealised_npr != null && (
              <li>
                Worth about {rupees(pos.value_after_gap_npr)} if sold back today:{" "}
                <span className={pos.unrealised_npr < 0 ? "text-wait" : "text-buy"}>
                  {pos.unrealised_npr < 0 ? "down" : "up"} {rupees(Math.abs(pos.unrealised_npr))}
                </span>
              </li>
            )}
          </ul>
        ) : (
          <p className="text-ink-2">Nothing open.</p>
        )}
        {pos.realised_npr !== 0 && (
          <p className="num mt-2 text-[15px]">
            Closed trades so far:{" "}
            <span className={pos.realised_npr < 0 ? "text-wait" : "text-buy"}>
              {pos.realised_npr < 0 ? "lost" : "made"} {rupees(Math.abs(pos.realised_npr))}
            </span>{" "}
            <span className="text-ink-2">(from the sale prices you entered)</span>
          </p>
        )}
      </Section>

      <Section title="Your trades">
        <TradeLog asset={asset} trades={t.trades} nepalPrice={t.nepal_price} />
      </Section>

      <Section title="Two-year test of this plan" updated={t.replay?.computed_at}>
        {t.replay?.results.length ? (
          <>
            <ul className="divide-y divide-line">
              {t.replay.results.map((r) => (
                <li key={r.gap_pct} className="num flex flex-wrap items-baseline justify-between gap-x-3 py-2">
                  <span>Buy-back gap {r.gap_pct}%</span>
                  <span>
                    {r.trades} trades, {r.winning} made money ·{" "}
                    <span className={`font-semibold ${r.total_npr < 0 ? "text-wait" : "text-buy"}`}>{signed(r.total_npr)}</span>
                  </span>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs leading-relaxed text-ink-2">
              A replay of today&apos;s rule on past prices from {longDate(t.replay.results[0].first_day)} to{" "}
              {longDate(t.replay.results[0].last_day)}, with {rupees(t.replay.budget_npr)}, buying at Nepal&apos;s published price and selling
              back at that price less the gap. A simulation, not real results. Updated {stamp(t.replay.computed_at)}.
            </p>
          </>
        ) : (
          <p className="text-ink-2">Not run yet. It runs once a day.</p>
        )}
      </Section>

      <Section title="Budget and buy-back gap">
        <TradeSettingsForm asset={asset} budget={t.budget_npr} gapPct={t.gap_pct} />
      </Section>
    </AppShell>
  );
}
