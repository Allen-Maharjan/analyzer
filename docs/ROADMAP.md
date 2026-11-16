# Roadmap

**Revamp (planned 2026-11-16):** fresh data, concrete answers, a track record page, silver trading with alerts, and a new look. The build spec, with measurements and acceptance checks per phase, is in `docs/REVAMP_SPEC.md`.

## Revamp status (2026-11-16)

| Phase | Built | Waiting on the owner |
|---|---|---|
| 1 Fresh data | Outside-timer endpoint, self-refresh on open, live world price, honest ages, holiday verdict (rules-6), two-source cross-check | Set up cron-job.org (`docs/ARCHITECTURE.md`); then re-measure the schedule over 3 weekdays |
| 3 Track record | Page, API, tests | Nothing |
| 2 Concrete answers | "Where the price is", rupee floors and ceilings, US announcements, Today order; two-part buying built and **off** | Decision on two-part buying (numbers below) |
| 4 Silver trading and alerts | Trade screen (trial), trades, two-year replay, Web Push | Approve or reject the trade rule (numbers below); create VAPID keys; test on phones |
| 5 New look | Three samples in `docs/design-samples/` | Pick a sample |

**Rules-6 (Phase 1.5):** a Nepal holiday with a healthy collector no longer blocks the verdict. The two-year replay judges publication days only, so it did not move: gold 617 days (348 BUY, 104 WAIT, 165 WATCH CLOSELY), silver 617 days (295 / 126 / 196), identical day by day before and after; following the advice cost +0.02% (gold) and −0.29% (silver) against buying on the first day of each week, as before.

**Two-part buying (Phase 2.3), replay 2024-11-05 to 2026-11-15, same 88 weekly periods per metal, per tola, fees not included:**

| | One purchase on the first BUY | Two-part rule | Weeks the rule applied | Two-part cheaper in |
|---|---|---|---|---|
| Gold | +0.02% vs the week's first day | +0.12% | 33 | 16 of 33; on average Rs 624 per tola more |
| Silver | −0.29% | −0.13% | 25 | 10 of 25; on average Rs 23 per tola more |

Two-part buying did not beat one purchase for either metal, so it ships switched off (`decision/split.py` `ENABLED = False`, rules version stays rules-6). The code, the plan columns (migration 0006) and the "I bought the first half" action are in place if the owner wants it anyway. Owner decision: pending.

**Silver trade rule (Phase 4.1), replay 2024-11-05 to 2026-11-15 on Rs 1,00,000, buying at Nepal's price and selling back at that price less the gap:**

| Buy-back gap | Trades | Made money | Total |
|---|---|---|---|
| 0% | 26 | 18 | +Rs 21,236 |
| 2% | 26 | 13 | −Rs 25,188 |
| 4% | 26 | 7 | −Rs 71,613 |

With any realistic buy-back gap the rule loses money. The Trade screen says so in its first sentence and labels the plan "Trial only" (`trading.APPROVED = False`). Owner decision: pending.

The full specification was agreed on 2026-11-02. It is split into phases so each one is usable and tested before the next starts.

## Phase 1: data foundation (built)

Docker Compose, PostgreSQL with TimescaleDB, Redis, Celery worker and beat, FastAPI, Alembic migrations. Collectors for Gold API, Dukascopy, FENEGOSIDA, NRB, and FRED. Source-health API.

Remaining Phase 1 sources: DXY (Yahoo, best effort), Fed/BLS/BEA calendars, Fed statements and speeches, World Gold Council releases.

## Phase 2: analytics and purchase rules (built)

Not yet: DXY in the macro score (dollar weight contributes zero until collected), AI adjustment.


Indicators (TA-Lib), confirmed pivots and support/resistance, touch / intrabar breach / confirmed break / reclaim states, the auditable forecast score, Nepal lag and premium, and the BUY / WAIT / WATCH CLOSELY decision rules with their acceptance tests.

## Phase 3: dashboard (built)

Built: Today, Details, Settings, sign-in. Reverse proxy and HTTPS move to Phase 4 with Web Push. Performance view moves to Phase 5.


Next.js views: Overview, Analysis, Performance, Settings. Owner login, sessions, CSRF, reverse proxy with HTTPS.

**Plain-language first (owner requirement, 2026-11-02).** The owner is not a trader. Every screen and every AI analysis must:

- Lead with a short plain-language summary: what to do, why in one or two everyday sentences, and when to check again. No jargon such as RSI, MACD, ATR, or "confirmed break" in the summary.
- Put the technical detail (indicators, scores, levels, scenarios, evidence) behind a clearly labelled button such as "View detailed analysis", on a separate view or expandable panel.
- Explain any unavoidable term inline in plain words.

## Phase 4: AI analysis and alerts (AI built; alerts next)

Built 2026-11-02: AI runner, schema validation, ±5 adjustment, schedule, Settings. Also built early from Phase 5: empirical 24 h / 3 d / 7 d scenarios. Still to do: browser notifications, Web Push, HTTPS.


Codex / Claude Code / Kiro CLI runner on the host, schema-validated output, ±5 point adjustment limit. The AI output contract includes a required `plain_summary` field (short, jargon-free) separate from the detailed analysis, to satisfy the plain-language requirement above. Browser notifications and Web Push; alert notifications use the plain-language summary.

## Phase 5: forecasts and evaluation

Empirical analogue scenarios for 24 h / 3 d / 7 d, immutable forecast storage, maturity evaluation, calibration, Brier score, walk-forward backtests.

Built 2026-11-04 (ported from Freqtrade's backtesting and lookahead-analysis ideas, no Freqtrade code): `gold-advisor backtest` replays the current rules day by day on point-in-time data and reruns sampled days on cut-off history to prove nothing from the future leaked in.

Rules-4 (2026-11-04, owner-approved): BUY no longer needs Nepal's price to have dropped first. On the two-year replay this cut the cost of following the advice, against buying on the first day of each 7-day period, from +0.53% to +0.07% for gold and from +0.48% to −0.04% for silver. BUY now appears on about half of all days (gold 335 of 611 days, silver 262 of 611). The FOMC WAIT rule stays: prices fell 1.5% (gold) and 2.9% (silver) over the five price updates after it. Rules-5 (same day, owner-approved): a pending *rise* in Nepal's price no longer blocks BUY, since today is then the cheaper day; replay cost +0.02% for gold and −0.30% for silver. Next from the same port: extra strategy signals, a LightGBM forecaster (evidence only, never the decision), and chart indicator overlays.

**LightGBM direction forecaster (built and tested 2026-11-16, not wired in):** `gold-advisor ml-forecast --asset gold|silver` (`analytics/ml_forecast.py`, optional `backend[ml]` extra, read-only). It learns "higher or lower in 1, 3, 5 trading days" from daily candles of both metals and FRED rates (lagged a day), retrained monthly and judged only on the next unseen month, 2019-2026 (about 1,820 test days per horizon). Result: **no edge.** Gold was right 52-53% against 53-56% for always guessing "up"; silver 50-52% against 52-54%. Its probabilities were worse than the base rate (Brier 0.26-0.28 vs 0.25 for gold, 0.26-0.29 for silver). A much simpler setting just learned "usually up" and tied the baseline. Do not show its forecast as a prediction or feed it to the rules or the AI unless a future version beats both baselines on this test.
