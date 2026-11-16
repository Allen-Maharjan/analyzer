# Revamp build spec

Written 2026-11-16. For an agent picking up one phase at a time. Read `AGENTS.md`, `docs/ARCHITECTURE.md` and `PRODUCT.md` first; this file does not repeat them.

| Phase | What | Status |
|---|---|---|
| 1 | Fresh data | Built 2026-11-16; owner sets up cron-job.org |
| 2 | Concrete answers on the Today screen | Built 2026-11-16; two-part buying off (replay below one purchase), see `docs/ROADMAP.md` |
| 3 | Track record page | Built 2026-11-16 |
| 4 | Silver trading and browser notifications | Built 2026-11-16; trade rule is a trial (replay loses money after the gap); VAPID keys needed |
| 5 | New look | Samples in `docs/design-samples/`; waiting for the owner's choice |

Order: 1, then 3 and 2 (independent of each other), then 4. Phase 5 can run beside 2 once the Today layout is settled. Phase 4 needs the regular cycles from Phase 1.

## Owner decisions (2026-11-16)

| Question | Answer |
|---|---|
| May the app advise buying gold in two parts? | Yes. This replaces "never recommend splitting" in `PRODUCT.md`. Never more than two parts. |
| A Trade screen? | Yes, for silver only, with a budget of Rs 1,00,000. Gold is bought for festivities and never gets sell advice. |
| Alerts | Browser notifications (Web Push). |
| Outside timer | cron-job.org. |
| Look | Wants stronger colours than the plain look chosen on 2026-11-02. Direction not chosen yet (Phase 5). |

## Why: what was measured (4–16 Nov 2026)

| Problem | Measurement |
|---|---|
| Scheduled runs are dropped | `collect.yml` has 48 cron slots a day. GitHub started 1–5 scheduled runs a day (42 in 13 days). Median gap between scheduled runs 375 min, 90th percentile 509 min, longest 1,496 min. All 69 runs that did start succeeded; the 27 `workflow_dispatch` runs started promptly. |
| No verdict during a Nepal holiday | 27 of 105 snapshots per asset (26%) used rule `data` ("Hold off: some prices are out of date"). FENEGOSIDA published nothing on 10–12 Nov (after 9 Nov, next 13 Nov), so `freshness.nepal_publication` returned STALE and `analysis._essential_issues` blocked every rule. |
| The dashboard hides the age | `/api/v1/dashboard` serves the latest snapshot unchanged. Source statuses are frozen at snapshot time, so a 6-hour-old snapshot still says "up to date". |
| Refresh reports success too early | `web/src/components/RefreshButton.tsx` waits 8 s and says "Checked. Showing the latest advice." A cloud run takes 2–4 min. |
| The forecast is good but invisible | Next Nepal price, last snapshot before each publication: gold mean absolute error 0.27% (n=7, 6 inside the stated range), silver 0.69% (n=7, 6 inside). No screen shows this. |

The repository is public (`gh repo view --json isPrivate` returns `false`), so GitHub Actions minutes are unlimited. `docs/ARCHITECTURE.md` still describes the 2,000-minute private quota; correct it in Phase 1.

To re-measure the schedule after a change:

```bash
gh run list --workflow collect.yml -L 200 --json createdAt,event,conclusion > runs.json
python3 - <<'EOF'
import json, datetime as dt, collections
r = json.load(open("runs.json"))
p = lambda s: dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
s = sorted(p(x["createdAt"]) for x in r)          # all triggers, not only "schedule"
for d, n in sorted(collections.Counter(t.date() for t in s).items()): print(d, n)
g = sorted((b - a).total_seconds() / 60 for a, b in zip(s, s[1:]))
print("median", g[len(g) // 2], "p90", g[int(len(g) * .9)], "max", g[-1])
EOF
```

## Rules for every phase

- The rules in `docs/ARCHITECTURE.md` ("Rules that must survive changes") hold. The ones most at risk here: no invented data, snapshots are immutable, free sources only, the AI only explains.
- Neon is production. Reads are fine. Schema changes go through Alembic migrations in `backend/migrations/` and must be additive. Never update or delete rows in `analysis_snapshots`, `local_metal_rates`, `candles` or `spot_quotes`.
- A change to BUY / WAIT / WATCH CLOSELY logic needs a new rules version, a before/after `gold-advisor backtest` for both assets, and the owner's approval of the numbers before merge.
- Plain language first on every screen. Jargon stays behind "View detailed analysis".
- Never print or commit secrets. New secrets are named here; the owner sets their values.
- Read a file before changing it; other agents and the owner edit this repo.
- The owner prefers few new tests: add tests only where a rule or a calculation changes.

Verify with:

```bash
cd backend && .venv/bin/pytest -m 'not integration'
cd web && npm run build
# After backend response models change (API running locally on :8010):
cd web && npm run gen:api
```

`backend/.python-version` pins 3.12, which pyenv may not have on the owner's machine. Use `backend/.venv/bin/python`, not bare `python3`, inside `backend/`.

---

## Phase 1: fresh data

Goal: when the owner opens the app, the world price is seconds old, the advice is at most about 30 minutes old, and its true age is always shown.

### 1.1 A timer that fires

GitHub's `schedule:` trigger is the fault, so start the same workflow from outside through `workflow_dispatch`, which works.

Backend (`backend/src/gold_advisor/api.py`, `config.py`):

- Add `ensure_fresh(session, now) -> tuple[bool, str]`. It starts a cycle through the existing `dispatch_cycle(force_daily=False)` only when all of these hold, and returns `(started, reason)`:
  - the newest `analysis_snapshots.created_at` is more than 20 minutes old;
  - `cooldown_passed(session, "cycle", 600)`;
  - it is not Saturday in Nepal. The workflow's own Saturday skip applies only to `schedule` events, so this check must live here. Today the rule exists only as shell in `collect.yml` ("Skip Saturday (Nepal time)"). Write it once as a Python function beside `cycle.world_market_active` and add its cases to `backend/tests/test_cycle_schedule.py`.
- Add `POST /api/v1/cron/tick`. It calls `ensure_fresh` and returns `{"started": bool, "reason": str}` with status 200 in every non-error case.
  - Auth: a new setting `cron_token` (env `GA_CRON_TOKEN`), compared with `hmac.compare_digest` against an `Authorization: Bearer` header. Exempt this path from `require_internal_token` the way `/api/v1/runner/` is. The timer must never hold `GA_INTERNAL_TOKEN`, which opens the whole API.
  - With `GA_CRON_TOKEN` empty the endpoint returns 404.
- Keep the three `schedule:` lines in `collect.yml` as a fallback. `ensure_fresh` and the workflow's `concurrency` group already prevent double work.

Owner setup on cron-job.org (free), to be written into `docs/ARCHITECTURE.md` as numbered steps in plain words. The agent cannot do these; the owner must:

1. Generate a long random value and add it as `GA_CRON_TOKEN` in the `analyzer-api` Vercel project, then redeploy.
2. Create a cron-job.org account and one job: URL `https://<analyzer-api>/api/v1/cron/tick`, method POST, header `Authorization: Bearer <the value>`, time zone Asia/Kathmandu, minutes 0 and 30 of every hour, every day.
3. Turn on the job's failure e-mail.

The endpoint must answer within a few seconds (it only starts the GitHub run), well inside the service's request time limit.

### 1.2 Self-heal when the app is opened

- Add `POST /api/v1/refresh/auto` (internal-token auth like the other routes). It calls `ensure_fresh` and returns the same shape as `/cron/tick`.
- Web: a small client component on the Today and Details pages calls it once on load through a new route handler under `web/src/app/api/`. If `started` is true, show a quiet line ("Getting the latest prices, about 3 minutes") and poll the dashboard every 20 s until `created_at` changes or 6 minutes pass, then `router.refresh()`.
- Fix `RefreshButton.tsx` the same way: poll for a new `created_at`. Say "Showing the latest advice" only after it changes. On timeout say the update is still running.

### 1.3 Live world price on open

- Add `GET /api/v1/live?asset=`. It returns the world price, `observed_at`, source, whether the market is open, and a live estimate of Nepal's next price.
  - Price: reuse the collectors in `collectors/gold_api.py` and `collectors/swissquote.py` (primary, then backup), with a total time limit of 8 s. Make at most one upstream call per asset per 60 s: serve the newest `spot_quotes` row when it is under 60 s old, otherwise fetch and store it through the existing persistence path. GET handlers get a read-only session (`get_session`), so the write needs its own `session_scope`.
  - Estimate: the same formula as `decision/nepal.forecast_next`, `reference_now × (1 + latest.premium)`, using the live price and the newest stored USD/NPR. Reuse the function; do not copy the arithmetic. Return the range too.
  - If both sources fail, return `available: false` with no numbers. Never fall back to an older price presented as live.
- This endpoint never writes a snapshot and never changes the decision. The decision comes only from a full cycle.
- Web, Today page: show "World gold now" with its age in seconds or minutes, and the live estimate in the existing "Expected at Nepal's next update" box, labelled as live. Refresh every 60 s while the tab is visible. When `available` is false, show the snapshot's value with its real age.

### 1.4 Honest ages on the dashboard

- `/api/v1/dashboard`: add `age_seconds` (now minus snapshot `created_at`) and recompute each source's status at request time with the functions in `freshness.py`, in place of the status stored in the snapshot.
- Today page: when the advice is older than 45 minutes while the world market is open, show a banner with the age in plain words ("This advice is 6 hours old. Getting a newer one."). It pairs with 1.2.

### 1.5 A verdict when Nepal has not published (rules change)

Today a missing Nepal publication is treated as broken data. During Tihar that removed the verdict for three days, although the collector was healthy and the next-price forecast was accurate (predicted Rs 2,70,800 for 13 Nov, actual Rs 2,71,700).

- Separate "the source failed" from "the source answered and has nothing new". The first stays an essential issue. The second is not: the decision goes through the normal rules, which already handle a world move since the last publication (`intl_decline_unpublished`, `expected_higher_next`, `expected_lower_next`).
  - "Answered, nothing new" means the `fenegosida` today-collector's last success is under 2 hours old and its newest `rate_date` is behind `expected_nepal_publication_date`.
  - Add a `limitations` line in plain words, for example: "Nepal has not published a new price since 9 Nov, possibly a holiday. Shops may be closed or using the old price."
  - After 7 days with no publication, treat it as an essential issue again.
- The change touches `freshness.nepal_publication`, `analysis._essential_issues` and their callers. Bump the rules version (`rules-6`) and `VERSION` where the freshness meaning changes.
- Tests: one case built from the real 9–13 Nov 2026 sequence showing a non-`data` rule on 10, 11 and 12 Nov, and one showing a failed collector still produces `data`.
- `gold-advisor backtest` judges publication days only, so its numbers should not move. Run it before and after for both assets and report both, to prove that.

### 1.6 Cross-check the world price

- In the cycle, collect both spot sources for each asset every run. Swissquote's last success was 4 Nov because the backup is only tried when the primary fails.
- When both are fresh and differ by more than 0.5%, record a quality flag and add an essential issue: "Two price sources disagree about the world price."
- Reject a quote that jumps more than 5% from the previous stored quote within 30 minutes unless the other source confirms it within 0.5%. Store the rejected value with a quality flag; do not use it as the current price.
- Each source's failure stays isolated (`cycle._step`).

### 1.7 Documents

Update `docs/ARCHITECTURE.md` (trigger diagram, `GA_CRON_TOKEN`, public repo and unlimited minutes, timer setup steps), `PRODUCT.md` "Operating Context" (it still says prices refresh every minute and analysis runs every 15 minutes) and `docs/ROADMAP.md`.

### Phase 1 is done when

- Over three consecutive weekdays, at least 40 cycles a day start, the median gap is 35 minutes or less and the longest gap is 90 minutes or less (script above).
- Opening the Today page while the market is open shows a world price under 2 minutes old.
- Opening the app with a snapshot older than 20 minutes starts a cycle, and the page updates itself when it finishes.
- No screen calls data "up to date" when it is older than its freshness limit.
- A day on which Nepal publishes nothing, with a healthy collector, still gets a rule-based verdict with the limitation line.
- With gold-api.com blocked, the live price comes from Swissquote; with both blocked the page shows the snapshot price with its age and no "live" label.
- Unit tests and the web build pass, and one real cycle succeeds.

### Out of scope for Phase 1

A second candle source, Web Push, any change to the Today layout beyond the lines named above, and any change to the AI step.

---

## Phase 3: track record page

Goal: the owner can check the app against what really happened, in rupees, without trusting anyone's word.

`PRODUCT.md` forbids invented performance claims. Everything on this page is computed from stored snapshots and published prices, always shows its sample size, and says so when the sample is small.

### 3.1 Data

No new tables. Compute at request time from `analysis_snapshots` and `local_metal_rates` (`source='fenegosida'`, `unit='tola'`, the asset's purity). Put the calculation in a new pure module, `backend/src/gold_advisor/analytics/track_record.py`, that takes rows and returns dataclasses, so it can be tested without a database. Use `market_data.normalized_payload` to read snapshots; older payloads differ in shape.

**Forecast record.** For each published Nepal price with rate date D:

- take the last snapshot created before that price's `published_at` (or before 10:45 Nepal time on D when the time is unknown) whose `prices.nepal_latest.rate_date` is earlier than D and which has `prices.nepal_next`;
- record `estimate`, `low`, `high`, the actual price, the error in rupees and percent, whether the actual fell inside the range, and how many hours before publication the snapshot was made;
- skip the day when no such snapshot exists. Never fill gaps.

Summary: count, mean absolute error (percent and rupees), share inside the range.

**Advice record.** For each publication day D:

- the advice standing at 12:00 Nepal time on D (the same instant as `backtest.DECISION_TIME`): the last snapshot at or before it. Apply no news-risk override; show what the rules said;
- the Nepal price on D, and the lowest, highest and last price over the next 5 publications;
- an outcome in plain words, derived from those numbers only: for WAIT, "price fell Rs X within 5 updates" or "price did not fall; waiting cost Rs X"; for BUY, "a later price was Rs X lower" or "this was the lowest price of the next 5";
- days with fewer than 5 later publications are shown as "still open".

Summary: pass the same observations to the existing `analytics.decision_evaluation.evaluate`. It needs 20 complete windows; until then show its status and "n of 20 weeks collected" in place of a number.

### 3.2 API

`GET /api/v1/track-record?asset=&limit=60` with typed response models in `api.py`: a `forecast` block and an `advice` block, each with `summary` and `rows`, newest first. Regenerate `web/src/lib/api-types.ts`.

### 3.3 Web

- New page `web/src/app/track-record/page.tsx` and a fourth tab in `web/src/components/Nav.tsx`.
- Lead with two plain sentences built from the summaries, for example: "Over the last 7 price updates, the app's guess for the next Nepal gold price was off by Rs 750 on average. 6 of the 7 landed inside the range it gave."
- Then two lists, forecast and advice, laid out for a phone: one row per day with date, predicted, actual and difference; green or red always paired with words.
- Under 20 forecast rows, show "Small sample: n days" beside the summary.
- Empty state when nothing can be computed yet. Loading state like `web/src/app/details/loading.tsx`.
- Use the existing colour tokens in `web/src/app/globals.css`. Phase 5 restyles every page; do not start a new visual direction here.
- Today page: one line under the expected-price box linking to the page ("How accurate has this been?").

### 3.4 Optional, only if 3.1–3.3 are finished

Show the two-year replay from `gold-advisor backtest` in a separate section clearly titled as a simulation of the current rules on past data, not as live results. It is too slow for a request: run it once a day in the cycle and store the result in `app_settings`.

### Phase 3 is done when

- The page shows both lists for gold and silver from real data, with sample sizes.
- The forecast summary can be reproduced by hand from the listed rows.
- Reference values on 2026-11-16, from a looser pairing rule (last snapshot whose latest Nepal date was the previous publication): gold 0.27% mean absolute error over 7 days with 6 in range, silver 0.69% with 6 in range. The stricter rule above may differ slightly; a large difference means a bug.
- A day without a qualifying snapshot is absent from the list, not estimated.
- Unit tests for `track_record.py` cover: a normal day, a day with no earlier snapshot, a publication with unknown time, and an advice row with fewer than 5 later publications.

---

## Phase 2: concrete answers on the Today screen

Goal: the Today screen says where the price stands, which rupee levels matter, and exactly what would make the owner buy or wait, without opening Details.

Most of the inputs already exist in each snapshot: `timeframes[tf].levels` and `level_states` (support and resistance with touch counts), `rupees_per_usd_oz` (world dollars to Nepal rupees per tola, including today's gap), `forecasts`, `nepal_lag.recent_high`, `next_event`. This phase adds a few computed facts and surfaces them.

New keys in the snapshot payload are fine: only new snapshots carry them, old rows are never rewritten, and `market_data.normalized_payload` must give old snapshots a safe default.

### 2.1 "Where the price is"

Add a `position` block to the snapshot (computed in `analysis.py`, pure helpers in `analytics/`):

- Nepal price against the lowest and highest of the last 30 publications, in rupees.
- World price against its 52-week low and high, and the number of completed daily bars since the last new 52-week low.
- One plain sentence built from those numbers, for example: "Gold is Rs 2,600 above its lowest price since October and has not made a new low for 4 days."

### 2.2 Floors and ceilings in rupees

- Add a `key_levels` block: the two nearest supports below and the two nearest resistances above the current world price. Take them from the 1D levels first, then 4h, then 1W, skipping any within 0.3% of one already chosen.
- For each: the world price, the rupee value (`price × rupees_per_usd_oz`, rounded to Rs 500 for gold and Rs 5 for silver), the touch count and the current state from `level_states`.
- Today page: a short list, "Floor about Rs 2,67,500 (held twice)", "Ceiling about Rs 2,75,500". Always "about": the rupee value moves with the dollar rate and Nepal's gap. World dollar values stay in Details.

### 2.3 Buying in two parts (rules change, owner-approved in principle 2026-11-16)

Gold may be bought in two parts. Silver buying advice follows the same rule; the Trade screen in Phase 4 is separate.

- When the decision is BUY and the world outlook is bearish (the score's `outlook`) or a paused breakdown is listed in the risks, the advice becomes "Buy half now", with three plain triggers for the second half:
  - a dip trigger: the nearest floor from 2.2 ("if Nepal's price drops to about Rs X");
  - a recovery trigger: the nearest ceiling from 2.2 ("if it rises past about Rs Y, the fall is probably over");
  - a deadline: the day before the next `major` or `high` importance event in `economic_events` within 14 days, otherwise 7 days.
- When the decision is BUY and the outlook is neutral or bullish, the advice stays "buy the whole amount".
- WAIT and WATCH CLOSELY are unchanged.
- These conditions are a starting point. Before merge, extend `backtest.py` to compare, over the two-year replay and for both metals, one purchase on the first BUY against the two-part rule, and give the owner the cost of each in percent and rupees. Ship the version the numbers support. If two-part buying does not beat one purchase, say so and keep one purchase.
- Plan state: `purchase_plan` needs to know the first half was bought. Add nullable columns by migration (for example `first_part_at`, `first_part_price`) and a third action beside `purchased` and `restart` in `/api/v1/plan/{action}`. The waiting clock still changes only by owner action.
- Bump the rules version. Update `PRODUCT.md` ("one complete gold purchase", "Never recommend splitting") and the docstring at the top of `decision/rules.py`.

### 2.4 Upcoming US announcements

- Today page: the next four rows of `economic_events` within 30 days, with Nepal date and time, and one fixed plain line per `event_type`:
  - `us_cpi`, `us_pce`: "US inflation report. Higher than expected usually pushes gold down; lower usually lifts it."
  - `us_jobs`: "US jobs report. Strong numbers usually push gold down; weak numbers usually lift it."
  - `fomc_decision`: "US interest-rate decision. The biggest scheduled mover; prices can jump either way. The app says WAIT in the day before it."
- If the calendar source is stale, show the existing limitation text and no rows.

### 2.5 Today page order

Advice panel, then "where the price is", then the Nepal price with the live estimate (Phase 1.3), then the two-part triggers when they apply, then floors and ceilings, then announcements, then the existing reasons, news and sources. Details keeps everything technical.

### Phase 2 is done when

- For gold and silver, the Today page shows the position sentence, at least one floor and one ceiling in rupees, and the announcement list, all from the latest snapshot.
- Every rupee level can be reproduced as world level × `rupees_per_usd_oz` from the same snapshot.
- A BUY in a bearish market shows "Buy half now" with a dip trigger, a recovery trigger and a deadline date; the owner can record the first half; the second-half triggers stay visible until the plan is completed.
- The backtest comparison for 2.3 is written into `docs/ROADMAP.md` with the owner's decision.
- Old snapshots still render (no errors from missing keys).

---

## Phase 4: silver trading and browser notifications

Build after Phase 1. Alerts are checked once per cycle, so they can be up to 30 minutes late; say so on the screen.

### 4.1 Trade screen (silver only)

The app never places orders. It shows a plan and records what the owner says they did.

- Mark the asset: a `tradable` flag on `AssetDefinition`, true for silver only. The Trade tab and API return 404 for other assets. Gold never shows sell advice anywhere.
- Settings (in `app_settings`, key `trade:silver`): budget in rupees (default 100000) and the shop's buy-back gap in percent. The gap has no default: until the owner enters it, the screen shows prices but no profit figures, and asks for it. Do not guess it.
- Trades: a new table by migration (`trades`: asset, side, quantity in tola, price per tola, time, note). The owner adds and corrects entries by hand.
- Plan: a `trade_plan` block in the silver snapshot with one state and its levels in rupees:
  - stay out; buy first half; buy second half; hold; take profit; cut the loss.
  - Starting rule, to be tested before it is shown as advice: first half when three completed daily bars make no new low and a daily close is back above the nearest broken floor; second half on a daily close above the next ceiling; take profit at the ceiling after that; cut the loss on a daily close below the low made before the first buy.
  - For each state show the quantity the budget buys, the profit at the target after the buy-back gap, and the loss at the cut-loss level.
- Honesty requirement: replay the rule over two years in `backtest.py` with a buy-back gap of 0%, 2% and 4%, and show the result on the Trade screen (number of trades, share that made money, total result in rupees on Rs 1,00,000). If the rule loses money after the gap, the screen says so in the first sentence. The owner approves the numbers before the plan is presented as advice.
- Profit and loss: the open position from `trades`, valued at the latest Nepal price less the buy-back gap, and the realised result of closed trades.
- Update `PRODUCT.md`: purpose, users ("to decide whether to make one complete gold purchase") and the three-word decision vocabulary now have a silver-trading exception limited to this screen.

### 4.2 Browser notifications (Web Push)

Free: delivery goes through the browser makers' own push services.

- Web: `manifest.webmanifest` and icons, a service worker in `web/public/` that handles `push` and `notificationclick`, and a "Turn on notifications" control in Settings that asks permission only when pressed, subscribes with the public key and posts the subscription to the API. Show whether this device is subscribed and a "Send a test" button.
- iPhone: Web Push works only after the site is added to the Home Screen. Settings must explain that in numbered plain steps when it detects iOS outside standalone mode.
- Backend: table `push_subscriptions` (endpoint unique, keys, created, last success, failure count), endpoints to add, remove and test a subscription, and `pywebpush` for sending. A subscription that answers 404 or 410 is deleted.
- Secrets, values set by the owner: `GA_VAPID_PRIVATE_KEY` and `GA_VAPID_SUBJECT` in GitHub repository secrets and in `analyzer-api` (the cycle sends alerts; the API sends the test), `NEXT_PUBLIC_VAPID_PUBLIC_KEY` in `analyzer-web`. Document how to generate the key pair. Without the keys the feature hides itself.
- What triggers a notification, each evaluated at the end of `cycle.main` and each firing once per event (store fired events in a new `alert_events` table with a unique key so reruns never repeat a message):
  - the advice changed (for example WAIT to BUY);
  - Nepal published today's price (with the change in rupees);
  - a second-half trigger from 2.3 was reached;
  - a level in the owner's watch levels was crossed;
  - the silver trade plan changed state.
- Text: the plain headline and one sentence, with the rupee figure. No jargon. Tapping opens the Today or Trade page for that asset.
- Settings: a switch per trigger type.
- A failure to send never fails the cycle (`cycle._step` pattern).

### Phase 4 is done when

- The Trade tab exists for silver only, shows the plan in rupees with quantity, target and cut-loss, and shows profit figures only after the buy-back gap is entered.
- The two-year replay result is on the screen and recorded in `docs/ROADMAP.md` with the owner's decision.
- Recording a buy and a sell produces the right position and realised result.
- On an Android phone and on a desktop browser: turning notifications on, "Send a test", and a real advice change each produce one notification. On an iPhone the same works after Add to Home Screen.
- Running the cycle twice in a row sends nothing the second time.

---

## Phase 5: new look

Goal: stronger colour and a clearer Today screen, on a phone first, in light and dark.

`DESIGN.md` describes the current system and may lag the code; `web/src/app/globals.css` holds the live tokens. The repo's design skill (`impeccable`) applies to this phase.

1. Samples first. Build two or three static versions of the Today screen with real numbers, in light and dark, and let the owner choose. Do not restyle the app before that choice.
2. Then update the tokens in `globals.css`, rewrite `DESIGN.md` to match, and apply the system to every page: Today, Details, Track record, Trade, Settings, sign-in, and the charts (`CandleChart.tsx`, `WorldChart.tsx`, `NepalPriceChart.tsx` take their colours from the tokens).
3. Dark mode follows the device setting, with a manual choice in Settings.

Fixed constraints:

- Green means BUY, red means WAIT, amber means WATCH CLOSELY, always with a word and an icon.
- WCAG AA contrast in both themes; tap targets at least 44 px; readable without zoom; no horizontal scrolling on a 360 px wide phone.
- Rupees in Nepali digit grouping (`web/src/lib/format.ts`).
- Update "Brand Commitments" in `PRODUCT.md` with the chosen direction and date.
- No change to what the app says or computes in this phase.

Phase 5 is done when the owner has approved the chosen sample, every page uses the new tokens in both themes, `DESIGN.md` matches the code, and the web build passes.
