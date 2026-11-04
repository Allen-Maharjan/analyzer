# Roadmap

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
