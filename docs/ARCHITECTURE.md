# Architecture

Last updated 2026-11-16. Read this before changing how the app is deployed, scheduled, or stored.

The app runs in two modes over the **same Python code and the same Neon database**:

| Mode | Scheduler | Where code runs | AI | Status |
|---|---|---|---|---|
| **Cloud** (live since 2026-11-03) | cron-job.org every 30 min (GitHub cron as fallback) | GitHub-hosted runner; API and dashboard on Vercel | OpenRouter free models | Working |
| **Local** (original) | Celery beat | Docker Compose on the owner's computer | Codex / Claude Code / Kiro / OpenRouter via the host runner | Working; now writes to Neon |

Both modes are idempotent, so running them at the same time is safe but wasteful. With the cloud mode live, stop the local scheduler with `docker compose stop worker beat`.

## Cloud mode

```
Three ways a cycle starts, all ending in the same GitHub workflow_dispatch / schedule run:
  1. cron-job.org, minutes 0 and 30 Nepal time ─► POST analyzer-api /api/v1/cron/tick (Bearer GA_CRON_TOKEN)
  2. The owner opens Today or Details        ─► POST /api/v1/refresh/auto (the dashboard, internal token)
  3. GitHub's own cron (:15 and :45 UTC)       ─► fallback only: GitHub starts 1-5 of its 48 daily slots
  1 and 2 call ensure_fresh: start a cycle only if the newest snapshot is over 20 min old, no cycle
  was started in the last 10 min, and it is not Saturday in Nepal. The workflow's concurrency group
  stops two cycles overlapping. The Refresh and "Ask AI" buttons start a cycle directly.
  No scheduled runs on Saturday, Nepal time (no Nepal publication, world market closed);
  a late run that lands on Nepal's Saturday skips itself. Manual runs always go ahead.
  └─ .github/workflows/collect.yml
       ├─ install: uv pip install -e backend, npm ci in backend/dukascopy
       ├─ alembic upgrade head            (against Neon)
       └─ python -m gold_advisor.cycle    (backend/src/gold_advisor/cycle.py)
            1. collect   world spot from BOTH sources (Gold API and Swissquote) and cross-check them
                         (quotes.py: >0.5% apart is an essential issue; a >5% jump in 30 min that the
                         other source does not confirm is stored flagged and never used), then
                         15m/1h/1D candles per asset, only while the world market is
                         open or closed < 1 h ago (no chart updates over the weekend), then
                         Nepal today, NRB USD/NPR
                         FRED and FOMC every 6 h, US CPI/jobs/PCE release dates (FRED calendar)
                         daily, Nepal history daily (gated by last success)
            2. analyse   one immutable snapshot per asset (gold, silver), including Nepal's
                         expected next price (decision/nepal.py forecast_next: today's gap
                         carried forward; Nepal follows the ~9:45 am NPT world price) and its
                         80% range. Only FOMC forces WAIT; US data releases are listed as risks.
                         A Nepal holiday (collector succeeded < 2 h ago, nothing newer, under 7 days)
                         is not a data problem; the rules run with a limitation line (rules-6).
            3. AI        only if significant: advice changed, new Nepal publication,
                         world price moved >= 1% since the last AI run, or 12 h without AI.
                         Max 12 automatic runs per asset per Nepal day.
                         Calls runner/openrouter.py, then validates with ai/contract.py.
  └─ Neon Postgres (Singapore, Postgres 18, no TimescaleDB)

Vercel (two projects from this repo):
  analyzer-api  root backend/  FastAPI via backend/app.py; every call needs X-Internal-Token,
                               except /api/v1/cron/ (GA_CRON_TOKEN) and /api/v1/runner/ (runner token)
  analyzer-web  root web/      Next.js dashboard; calls analyzer-api server-side with the token
  Refresh and "Ask AI" buttons ─► API ─► GitHub workflow_dispatch (force_daily input)
  The cycle runs queued "Ask AI" jobs regardless of significance.
  GET /api/v1/live: world price seconds old for the Today page (newest stored quote if under 60 s,
  else one upstream call, primary then backup, 8 s budget) and Nepal's next price from it. It
  stores the quote but never writes a snapshot or changes the decision.
  GET /api/v1/dashboard re-judges each source's status at request time and returns age_seconds.

Planned, not built: nothing from the 2026-11-16 revamp spec except the Phase 5 restyle (samples in `docs/design-samples/`).

At the end of each cycle: browser notifications (alerts.py; each event stored once in `alert_events`,
so reruns never repeat a message) and, once a day, the two-year silver trade replay stored in
`app_settings` (`trade_replay:silver`) for the Trade screen.
```

### Deploying a change that adds a migration

Vercel deploys the API on push, before any GitHub run has migrated Neon. When a push adds a migration (0006 and 0007 were added on 2026-11-16), run the `collect` workflow once by hand ("Run workflow") right after pushing: its first step is `alembic upgrade head`. Until it finishes, `/api/v1/plan` and the Trade screen fail on the missing columns and tables.

### Browser notifications (Web Push), owner setup

1. Generate a key pair on any computer with Node: `npx web-push generate-vapid-keys`. It prints a public and a private key.
2. GitHub repository secrets: `GA_VAPID_PRIVATE_KEY` (the private key) and `GA_VAPID_SUBJECT` (`mailto:` and your e-mail).
3. Vercel `analyzer-api`: the same two values. Vercel `analyzer-web`: `NEXT_PUBLIC_VAPID_PUBLIC_KEY` (the public key). Redeploy both.
4. On each phone or computer: Settings > Notifications > "Turn on notifications", then "Send a test". On an iPhone, first add the site to the Home Screen and open it from there.

Without these values the Notifications section stays hidden and the cycle skips alerts.

### Outside timer (cron-job.org), owner setup

GitHub's `schedule:` trigger drops most runs, so a free outside timer starts the cycle. The agent cannot do these steps:

1. Generate a long random value (for example `openssl rand -hex 32`). Add it as `GA_CRON_TOKEN` in the `analyzer-api` Vercel project (Settings > Environment Variables), then redeploy.
2. Create a free account at cron-job.org and one job: URL `https://<analyzer-api domain>/api/v1/cron/tick`, method POST, header `Authorization: Bearer <the value>`, time zone Asia/Kathmandu, minutes 0 and 30 of every hour, every day.
3. In the job's settings, turn on the failure e-mail.

The endpoint answers in a few seconds: it only starts the GitHub run. A 200 response with `"started": false` is normal (advice still young, Saturday, or a run already started). Without `GA_CRON_TOKEN` it returns 404.

To check the schedule, run the script in `docs/REVAMP_SPEC.md` ("To re-measure the schedule").

### Secrets

| Where | Name | Purpose |
|---|---|---|
| GitHub repo secrets | `NEON_DATABASE_URL` | Direct (non-pooled) Neon connection string. Required. |
| GitHub repo secrets | `GA_OPENROUTER_API_KEY` | OpenRouter key. Optional; without it the AI step is skipped. |
| GitHub repo secrets | `GA_VAPID_PRIVATE_KEY`, `GA_VAPID_SUBJECT` | Web Push. Optional; without them no notifications. |
| Vercel `analyzer-web` | `NEXT_PUBLIC_VAPID_PUBLIC_KEY` | Web Push public key. Optional. |
| Vercel `analyzer-api` | `GA_DATABASE_URL` (Neon pooled URL), `GA_INTERNAL_TOKEN`, `GA_GITHUB_DISPATCH_TOKEN`, `GA_GITHUB_REPO`, `GA_CRON_TOKEN`, `GA_VAPID_PRIVATE_KEY`, `GA_VAPID_SUBJECT` | API, starting GitHub runs from the buttons, the outside timer (`/api/v1/cron/tick` only), and the "Send a test" notification |
| Vercel `analyzer-web` | `GA_API_URL`, `GA_INTERNAL_TOKEN`, `OWNER_PASSWORD`, `SESSION_SECRET`, `COOKIE_SECURE=true` | Dashboard |
| `.env` (local only, never committed) | the same two, plus `POSTGRES_PASSWORD`, `OWNER_PASSWORD`, `SESSION_SECRET`, `GA_RUNNER_TOKEN` | Local Docker stack and host runner |

Never print these values in logs or chat. `.env` is in `.gitignore`.

### Budgets and limits that shape the design

- **GitHub Actions:** the repository is public (`gh repo view --json isPrivate` returns `false`), so Actions minutes are unlimited. Each run takes about 1.5–2 minutes. GitHub's `schedule:` trigger is unreliable here: from 4 to 16 Nov 2026 it started 1–5 of the 48 daily slots (median gap 375 min), while every `workflow_dispatch` started promptly. Hence the outside timer.
- **Neon free plan:** 1 GB storage, 100 CU-hours/month, scales to zero after 5 min idle. The database was 31 MB on 2026-11-03; snapshots add about 12 kB each (about 210 MB/year at one per 30 min).
- **OpenRouter free models (`:free`):** 50 requests/day, 20/min on an account that never bought credits. Failed attempts count. Free models change often, so `runner/openrouter.py` discovers them from `/models` at run time (free price, text input, `structured_outputs` support) and tries up to 3.
- Free models are reasoning models: they need `max_tokens: 8000` and `reasoning: {effort: low}`, otherwise they stop at the token limit with empty content. Answers take 50–90 s. The whole AI call is capped at 270 s to stay inside the API's 5-minute "running" window (`ai/service.py` `RUNNING_TIMEOUT`).
- **Freshness:** a stored world quote counts as fresh for 35 min (`freshness.py` `LIVE_QUOTE_MAX_AGE`) because cloud runs are 30 min apart. The Today page's "World gold now" comes from `/api/v1/live` instead and is called live only when under 5 minutes old.

## Local mode

`docker-compose.yml`: `migrate`, `api` (FastAPI :8010), `worker` + `beat` (Celery, Redis), `web` (Next.js :3010), and a local `db` (TimescaleDB) kept as a backup. When `NEON_DATABASE_URL` is set in `.env`, every backend container uses Neon instead of `db`.

The host AI runner (`runner/gold_ai_runner.py`, systemd user service `gold-ai-runner`) claims queued AI jobs from the API and runs a signed-in CLI or OpenRouter. It exists because CLI sign-ins can't live inside containers or GitHub.

The dashboard (`web/`) reads data **through the FastAPI service** (`GA_API_URL`): locally the Docker `api` container, in the cloud the `analyzer-api` Vercel project.

## Code map

| Path | What lives there |
|---|---|
| `backend/src/gold_advisor/collectors/` | One module per source; each parses and validates its own payload and raises `SourceSchemaError` on shape changes |
| `backend/src/gold_advisor/jobs.py` | Collection jobs: fetch, persist, record a `collection_runs` row |
| `backend/src/gold_advisor/cycle.py` | The cloud cycle (collect, analyse, AI if significant) |
| `backend/src/gold_advisor/analysis.py` | Builds one immutable snapshot per asset |
| `backend/src/gold_advisor/analytics/` | Indicators (TA-Lib), levels, score, technical signals, scenario forecasts |
| `backend/src/gold_advisor/decision/` | Nepal lag/premium and BUY / WAIT / WATCH CLOSELY rules |
| `backend/src/gold_advisor/backtest.py` | Replays the rules over past Nepal publication days with point-in-time data, plus a look-ahead check. Run `gold-advisor backtest --asset gold` (read-only) |
| `backend/src/gold_advisor/ai/` | AI input facts, output schema, validation (`contract.py`) and job queue (`service.py`) |
| `backend/src/gold_advisor/assets.py` | Asset definitions (gold, silver): sources, units, thresholds |
| `backend/src/gold_advisor/freshness.py`, `health.py` | Freshness rules and source health |
| `backend/src/gold_advisor/quotes.py` | Cross-check of the two world-price sources |
| `backend/src/gold_advisor/live.py` | The live world price and next-Nepal-price estimate for `/api/v1/live` |
| `backend/src/gold_advisor/analytics/track_record.py` | Past forecasts and advice against published prices (Track record page) |
| `backend/src/gold_advisor/analytics/ml_forecast.py` | LightGBM up/down forecaster, `gold-advisor ml-forecast` only (optional `backend[ml]` extra). Experiment: tested with no edge, not used by the app |
| `backend/src/gold_advisor/analytics/macro_forecast.py` | 3- and 12-month forecasts on 2000+ history, `gold-advisor macro-forecast` only (fetches, never writes). Experiment: tested with no edge, not used by the app |
| `backend/src/gold_advisor/analytics/trade_signals.py` | Entropy and Kalman silver trade ideas, `gold-advisor trade-signals` only (fetches, never writes). Experiment: did not pass, not used by the app |
| `backend/src/gold_advisor/analytics/position.py`, `announcements.py` | "Where the price is", rupee floors and ceilings, upcoming US announcements |
| `backend/src/gold_advisor/decision/split.py` | Two-part buying (built, switched off) |
| `backend/src/gold_advisor/trading.py` | Silver Trade screen: plan states, the owner's trade book, the replay |
| `backend/src/gold_advisor/alerts.py` | Web Push notifications |
| `backend/migrations/` | Alembic. TimescaleDB is created only where available |
| `backend/migrate_to_neon.py` | One-off local-to-Neon data copy (refuses a non-empty target) |
| `runner/` | Host AI runner and `openrouter.py` (shared with the cloud cycle via `PYTHONPATH`) |
| `web/` | Next.js dashboard: Today, Details, Track record, Trade (silver), Settings, sign-in; `public/sw.js` handles notifications |
| `.github/workflows/collect.yml` | The cloud schedule |

## Rules that must survive changes

- **Plain language first.** Every screen and AI answer leads with a jargon-free summary; technical detail sits behind "View detailed analysis". See `docs/ROADMAP.md` and `PRODUCT.md`.
- **No invented data.** Missing or failed sources produce `unavailable` or `stale`, never seeded or carried-forward values. Gaps stay null.
- **Snapshots are immutable.** A database trigger blocks UPDATE and DELETE on `analysis_snapshots`.
- **The AI only explains.** It may move the score by at most ±5, cannot change the decision, and every price it quotes must match a computed fact within 0.5%. Invalid answers are stored for audit and not shown.
- **Free sources and free models only.** Do not add paid APIs or paid model fallbacks without the owner's approval.
- **The waiting clock resets only by owner action** (`/api/v1/plan/purchased` or `/restart`).
- **NRB is used only for USD/NPR**, never for gold prices. FENEGOSIDA is the Nepal gold source.

## How to verify a change

```bash
cd backend
.venv/bin/pytest -m 'not integration'                                   # unit tests
GA_DATABASE_URL="$NEON_DATABASE_URL" PYTHONPATH=../runner \
  .venv/bin/python -m gold_advisor.cycle                                # one real cloud cycle (writes to Neon)
```

Run `gold-advisor backtest --asset gold --compare-split` for the two-part comparison and `gold-advisor backtest --asset silver --trade` for the trade replay (both read-only; `--store-trade` writes the result for the Trade screen). The owner prefers few new tests; run the existing ones and one real cycle.
