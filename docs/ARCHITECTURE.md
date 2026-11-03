# Architecture

Last updated 2026-11-03. Read this before changing how the app is deployed, scheduled, or stored.

The app runs in two modes over the **same Python code and the same Neon database**:

| Mode | Scheduler | Where code runs | AI | Status |
|---|---|---|---|---|
| **Cloud** (live since 2026-11-03) | GitHub Actions every 30 min | GitHub-hosted runner; API and dashboard on Vercel | OpenRouter free models | Working |
| **Local** (original) | Celery beat | Docker Compose on the owner's computer | Codex / Claude Code / Kiro / OpenRouter via the host runner | Working; now writes to Neon |

Both modes are idempotent, so running them at the same time is safe but wasteful. With the cloud mode live, stop the local scheduler with `docker compose stop worker beat`.

## Cloud mode

```
GitHub Actions (cron :15 and :45 UTC = :00 and :30 NPT, e.g. 11:00 and 11:30; or "Run workflow")
  No scheduled runs on Saturday, Nepal time (no Nepal publication, world market closed);
  a late run that lands on Nepal's Saturday skips itself. Manual runs always go ahead.
  └─ .github/workflows/collect.yml
       ├─ install: uv pip install -e backend, npm ci in backend/dukascopy
       ├─ alembic upgrade head            (against Neon)
       └─ python -m gold_advisor.cycle    (backend/src/gold_advisor/cycle.py)
            1. collect   world spot + 15m/1h/1D candles per asset, only while the world market is
                         open or closed < 1 h ago (no chart updates over the weekend), then
                         Nepal today, NRB USD/NPR
                         FRED and FOMC every 6 h, Nepal history daily (gated by last success)
            2. analyse   one immutable snapshot per asset (gold, silver)
            3. AI        only if significant: advice changed, new Nepal publication,
                         world price moved >= 1% since the last AI run, or 12 h without AI.
                         Max 12 automatic runs per asset per Nepal day.
                         Calls runner/openrouter.py, then validates with ai/contract.py.
  └─ Neon Postgres (Singapore, Postgres 18, no TimescaleDB)

Vercel (two projects from this repo):
  analyzer-api  root backend/  FastAPI via backend/app.py; every call needs X-Internal-Token
  analyzer-web  root web/      Next.js dashboard; calls analyzer-api server-side with the token
  Refresh and "Ask AI" buttons ─► API ─► GitHub workflow_dispatch (force_daily input)
  The cycle runs queued "Ask AI" jobs regardless of significance.

Planned, not built:
  Neon Function cron trigger  ─► GitHub workflow_dispatch   (punctual start; Actions cron runs late)
  Web Push                    ─► phone notifications
```

### Secrets

| Where | Name | Purpose |
|---|---|---|
| GitHub repo secrets | `NEON_DATABASE_URL` | Direct (non-pooled) Neon connection string. Required. |
| GitHub repo secrets | `GA_OPENROUTER_API_KEY` | OpenRouter key. Optional; without it the AI step is skipped. |
| Vercel `analyzer-api` | `GA_DATABASE_URL` (Neon pooled URL), `GA_INTERNAL_TOKEN`, `GA_GITHUB_DISPATCH_TOKEN`, `GA_GITHUB_REPO` | API, and starting GitHub runs from the buttons |
| Vercel `analyzer-web` | `GA_API_URL`, `GA_INTERNAL_TOKEN`, `OWNER_PASSWORD`, `SESSION_SECRET`, `COOKIE_SECURE=true` | Dashboard |
| `.env` (local only, never committed) | the same two, plus `POSTGRES_PASSWORD`, `OWNER_PASSWORD`, `SESSION_SECRET`, `GA_RUNNER_TOKEN` | Local Docker stack and host runner |

Never print these values in logs or chat. `.env` is in `.gitignore`.

### Budgets and limits that shape the design

- **GitHub Actions:** 2,000 free minutes/month on a private repo. Each run is billed in whole minutes (about 1.5–2). 48 runs/day can exceed the private quota; a public repo has no limit. Scheduled runs often start 5–20 min late.
- **Neon free plan:** 1 GB storage, 100 CU-hours/month, scales to zero after 5 min idle. The database was 31 MB on 2026-11-03; snapshots add about 12 kB each (about 210 MB/year at one per 30 min).
- **OpenRouter free models (`:free`):** 50 requests/day, 20/min on an account that never bought credits. Failed attempts count. Free models change often, so `runner/openrouter.py` discovers them from `/models` at run time (free price, text input, `structured_outputs` support) and tries up to 3.
- Free models are reasoning models: they need `max_tokens: 8000` and `reasoning: {effort: low}`, otherwise they stop at the token limit with empty content. Answers take 50–90 s. The whole AI call is capped at 270 s to stay inside the API's 5-minute "running" window (`ai/service.py` `RUNNING_TIMEOUT`).
- **Freshness:** a live world quote counts as fresh for 35 min (`freshness.py` `LIVE_QUOTE_MAX_AGE`) because cloud runs are 30 min apart.

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
| `backend/src/gold_advisor/ai/` | AI input facts, output schema, validation (`contract.py`) and job queue (`service.py`) |
| `backend/src/gold_advisor/assets.py` | Asset definitions (gold, silver): sources, units, thresholds |
| `backend/src/gold_advisor/freshness.py`, `health.py` | Freshness rules and source health |
| `backend/migrations/` | Alembic. TimescaleDB is created only where available |
| `backend/migrate_to_neon.py` | One-off local-to-Neon data copy (refuses a non-empty target) |
| `runner/` | Host AI runner and `openrouter.py` (shared with the cloud cycle via `PYTHONPATH`) |
| `web/` | Next.js dashboard: Today, Details, Settings, sign-in |
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

The owner prefers few new tests; run the existing ones and one real cycle.
