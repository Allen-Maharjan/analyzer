# Nepal Gold Purchase Advisor

Private, self-hosted app that helps one household decide whether to buy gold now or wait briefly.

**Status:** Phases 1–3 of 5 are built: data collection, analysis, and the dashboard.

**Architecture (2026-11-03):** the app is moving to the cloud. GitHub Actions runs a collect, analyse and AI cycle every 30 minutes, the database is Neon Postgres, and the AI uses OpenRouter's free models. The local Docker stack below still works and now also uses Neon. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). AI agents: start with [AGENTS.md](AGENTS.md).

**Open the dashboard:** <http://localhost:3010>. The password is `OWNER_PASSWORD` in `.env`. To use it from your phone on home Wi-Fi, set `WEB_BIND=0.0.0.0` in `.env`, run `docker compose up -d web`, and open `http://<this computer's IP>:3010`. Plain HTTP on Wi-Fi sends the password unencrypted; HTTPS arrives with notifications in Phase 4.

## Run it

1. `cp .env.example .env`, then set `POSTGRES_PASSWORD` (`openssl rand -hex 24`), `OWNER_PASSWORD` (your sign-in password), and `SESSION_SECRET` (`openssl rand -hex 32`).
2. `docker compose up -d --build`
3. Backfill history once (about 20–40 minutes, mostly Dukascopy):
   `docker compose run --rm api gold-advisor backfill`
4. Check source health: `curl -s localhost:8010/api/v1/sources | jq`

After the backfill, the `beat` scheduler keeps everything current. Interactive API docs: <http://localhost:8010/docs>.

Ports bind to `127.0.0.1` only. The API has no login yet (Phase 3 adds owner authentication), so do not expose it to a network.

## What is collected

| Dataset | Source | Schedule | Backfill |
|---|---|---|---|
| XAU/USD live spot | Gold API; Swissquote public feed as backup when Gold API fails | every 60 s | none (live only) |
| XAU/USD candles 15m, 1h, 1D (bid) | Dukascopy via pinned `dukascopy-node` 1.51.1 | 15m / hourly / every 6 h | 90 days / 2 years / 10 years |
| XAU/USD 4h and 1W | derived from complete 1h and 1D bars | after each source run | from stored bars |
| Nepal hallmark gold and silver, per tola and per 10 g | FENEGOSIDA dashboard API | checks every 30 min 10:00–14:30 NPT until today's price is stored, then stops; history re-read daily | 36 months |
| USD/NPR buy and sell (exchange rate only, never gold prices) | NRB forex API | checks every 3 h until today's rate is stored, then stops | 10 years |
| FOMC rate decisions | federalreserve.gov calendar | every 6 h | all listed years |
| US 2y, 10y, 10y real yields | FRED (`DGS2`, `DGS10`, `DFII10`) | every 6 h | 10 years |

Not yet collected: DXY, BLS and BEA calendars (bls.gov blocks automated requests), Fed statements, World Gold Council releases.

Nepal gold and the dollar rate change once a day, so the app stops asking for them once today's value is stored. To re-check on demand (the dashboard's refresh button will call this):

```bash
curl -X POST localhost:8010/api/v1/refresh/nepal_gold   # or usd_npr; once per minute
```

## AI analysis

The AI writes a short plain-language take on the app's numbers. It uses the Codex, Claude Code, or Kiro CLI already signed in on this computer (pick one in Settings; Codex is the default). Nothing is billed separately, and the app never switches provider on its own.

- **Runner:** `runner/gold_ai_runner.py` runs on the host, not in Docker, so the CLIs keep their own sign-in. It is installed as a user service:
  `systemctl --user status gold-ai-runner` · logs: `journalctl --user -u gold-ai-runner -f`
- **Schedule:** every 4 hours and whenever the advice changes, at most 12 automatic runs a day. "Ask AI again" on Today runs it on demand (once a minute).
- **Limits:** one run at a time, 120-second timeout, an empty temporary folder, no tools or MCP servers, and only the app's computed numbers as input.
- **Checks:** the answer must match a fixed schema. Every price it quotes must match a number the app gave it (within 0.5%), and every cited evidence or level ID must exist. It may move the score by at most ±5 and cannot change BUY / WAIT / WATCH CLOSELY. Answers that fail are kept for audit but not shown.
- **Audit:** every run is stored in `ai_analyses` with provider, model, CLI version, prompt version, input, raw output, and validation result.
- **Setup on a new machine:** set `GA_RUNNER_TOKEN` in `.env` (`openssl rand -hex 32`), run `docker compose up -d api`, then install `runner/gold-ai-runner.service` as described at the top of that file. Kiro needs `kiro-cli login` first.

## Advice endpoints

| Endpoint | What it returns |
|---|---|
| `GET /api/v1/dashboard` | Plain-language advice: decision, headline, short summary, reasons (each with `plain` and `detail` text), prices, next review |
| `GET /api/v1/snapshots/{id}` | Full technical detail for that advice: indicators, levels, scores, Nepal premium |
| `GET /api/v1/plan`, `POST /api/v1/plan/purchased`, `POST /api/v1/plan/restart` | The waiting clock. Only these calls reset it |
| `GET/PUT /api/v1/settings/watch-levels` | Editable price levels to watch (default $4,000) |

Analysis runs every 15 minutes and after each Nepal or dollar-rate update.

### Source notes

- **FENEGOSIDA** currently publishes only hallmark gold (छापावाल सुन) and silver. There is no fine (tejabi) row, so hallmark is the Nepal reference. The API field `todayBaseRatePerGram` is misnamed: the value is per the unit in the label (1 tola or 10 g). Tola and 10 g prices are cross-checked and flagged `unit_mismatch` if they disagree. History rows have a date but no publication time; `publication_time_known` shows which is which.
- **NRB** serves the wrong TLS intermediate certificate. The app ships the correct Sectigo intermediate (`backend/src/gold_advisor/certs/`) and still verifies the full chain to a trusted root. The midpoint is exposed as `analytical_midpoint` for comparisons only.
- **Dukascopy** bars are bid prices, UTC-aligned. Daily bars close at 00:00 UTC. Weekly bars start Sunday 00:00 UTC so the Sunday evening session belongs to its week. Quote and candle providers are never mixed.
- **FRED** gaps (US holidays) stay null. They are never filled from the previous value.

## Freshness rules

Each dataset in `/api/v1/sources` reports data freshness and collector status separately, so a closed market is never mistaken for a broken collector.

| Status | Meaning |
|---|---|
| `fresh` | Current evidence. |
| `stale` | Older than the rule allows. Shown with its age; not valid evidence. |
| `market_closed` | Gold market is closed and the data covers the close. |
| `unavailable` | Nothing verified has been stored. |

- Live spot: stale after 35 minutes while the market is open (cloud runs are 30 minutes apart) (Sunday 18:00 to Friday 17:00 New York, daily break 17:00–18:00).
- Nepal: expected every Sunday–Friday by 12:00 NPT. A missed day is stale and notes a possible public holiday.
- NRB: yesterday's rate stays fresh until 18:00 NPT, because NRB sometimes publishes late.
- FRED: fresh up to 3 US business days behind.

Exchange holidays are not modelled yet. On those days, live data shows as `stale`, not `market_closed`.

## Data integrity

- Collection is idempotent. Re-collecting the same value changes nothing.
- A changed value increments `revision`. For Nepal rates, FX, and macro series, the old value is kept in `observation_revisions`.
- Every run is recorded in `collection_runs` with counts and errors.
- Each scheduled task holds a Redis lock, so slow runs never overlap.
- HTTP calls retry at most 3 times with backoff and honour `Retry-After`.
- Nothing is seeded. An empty database shows `unavailable` until real observations arrive.

## Tests

```bash
cd backend
uv venv -p 3.12 .venv && uv pip install -p .venv -e '.[dev]'
.venv/bin/pytest -m 'not integration'          # unit tests, no database
GA_TEST_DATABASE_URL=postgresql+psycopg://gold:<password>@localhost:55432/gold_test \
  .venv/bin/pytest -m integration              # wipes and migrates gold_test
```

Create the test database once: `docker compose exec db createdb -U gold gold_test`.

## Backup and restore

```bash
# Backup
docker compose exec -T db pg_dump -U gold -Fc gold > backup-$(date +%F).dump

# Restore into an empty database (stop worker and beat first)
docker compose stop worker beat api
docker compose exec -T db psql -U gold -d postgres -c "DROP DATABASE gold" -c "CREATE DATABASE gold"
docker compose exec -T db psql -U gold -d gold -c "CREATE EXTENSION timescaledb" -c "SELECT timescaledb_pre_restore()"
docker compose exec -T db pg_restore -U gold -d gold < backup-YYYY-MM-DD.dump
docker compose exec -T db psql -U gold -d gold -c "SELECT timescaledb_post_restore()"
docker compose start api worker beat
```

`DROP DATABASE` deletes the current data. Take a fresh backup before restoring.

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md).

## Gold and silver

The asset selector switches Today, Details, Settings, AI results, purchase plans, and watch
levels between gold and silver. On Details, the world chart offers 15-minute, hourly, and daily completed candles. It checks for updates every minute while visible; the separately labelled live spot quote is not used to create candles. Silver uses FENEGOSIDA pure silver, Gold API XAG/USD spot
(with Swissquote backup), and Dukascopy XAG/USD candles. Silver's initial buy and wait
thresholds use the same percentage rules as gold, without gold's fixed rupee trigger. They
are initial rules, not calibrated silver-specific thresholds.

For an existing installation, stop the API, worker and scheduler during the upgrade, back up
the database, then rebuild and restart with Docker Compose so the migration runs before the
new processes start. Backfill silver with `docker compose run --rm api gold-advisor backfill
--asset silver`; the job may take some time. `backfill --asset all` backfills both assets, and
`gold-advisor collect candles-1D --asset silver` runs one asset-specific collector. Existing
commands default to gold when collecting a single job. The migration retains gold snapshots,
waiting state, and watch levels. It refuses downgrade while non-gold data exists.

The API exposes `GET /api/v1/assets` and accepts `?asset=gold` or `?asset=silver` on market,
dashboard, plan, watch-level, and AI endpoints. Existing requests default to gold. The old
`nepal_gold` refresh target remains available; `nepal_rates` refreshes the shared feed.

### Adding a market adapter

Asset definitions in `backend/src/gold_advisor/assets.py` supply identifiers, units, provider
symbols, timeframes, market calendars, and analysis profiles. Market reads accept a bounded
`MarketQuery` in `backend/src/gold_advisor/persistence/market_data.py`; the provider adapter
must emit observations with the same instrument identity. A future NEPSE implementation needs
its own verified data adapter, exchange calendar, asset definitions, and equity analysis policy.
The shared candle query accepts NPR-per-share daily observations without metal conversion or
intraday bars. NEPSE collection and investment advice are not yet implemented.

### Local-price calibration experiment

Run `gold-advisor evaluate-local --asset gold` (or `silver`) against stored FENEGOSIDA
per-tola prices. The experiment selects a percentage drop threshold using the first 60%
of non-overlapping seven-day windows, then evaluates the selected threshold on the remaining
windows against purchasing immediately. It reports mean cost relative to immediate purchase,
regret relative to the lowest published price in each window, and the fraction of windows in
which waiting produced a lower price. It excludes fees, intraday prices, the live decision
engine and news; it uses the latest stored price revisions rather than point-in-time revisions.
Consequently it is an exploratory comparison, not proof of live decision performance, and it
does not automatically change production thresholds.

### OpenRouter free models

Set `GA_OPENROUTER_API_KEY` in the host runner `.env` file and restart the `gold-ai-runner` user service. Select OpenRouter in Settings. Each job discovers compatible `:free` models with zero advertised prices and sets a zero price ceiling. If none are available, the job fails without using a paid model. Free providers can rate-limit requests and may have their own data policies; review those before enabling the provider. The resolved model is stored with each result.

Run `gold-advisor evaluate-decisions --asset gold` (or `silver`) to compare saved,
point-in-time decisions with immediate purchase. It excludes incomplete and gapped
windows and reports no score until enough recorded days have accumulated. It cannot
reconstruct decisions from before snapshots existed.
