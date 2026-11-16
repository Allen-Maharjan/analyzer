"""The world price "now" for the Today page, and Nepal's next price estimated from it.

Read on request, so the owner sees a price seconds old instead of the last cycle's. This never
writes a snapshot and never changes the decision; the decision comes only from a full cycle.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from gold_advisor import analysis, freshness, jobs
from gold_advisor.assets import AssetDefinition
from gold_advisor.collectors.http import make_client
from gold_advisor.decision import nepal
from gold_advisor.domain import FreshnessStatus, Source, Timeframe
from gold_advisor.persistence import market_data
from gold_advisor.persistence.db import session_scope

log = logging.getLogger(__name__)

# Serve the newest stored quote when it is this young; at most one upstream call per asset this often.
CACHE = timedelta(seconds=60)
# While the market is open, an older quote is not called live (the page shows the snapshot instead).
MAX_AGE = timedelta(minutes=5)
FETCH_BUDGET_SECONDS = 8.0
SOURCES = tuple(source for source, _ in jobs.SPOT_SOURCES)


@dataclass(frozen=True)
class Live:
    available: bool
    market_open: bool
    price: float | None = None
    observed_at: datetime | None = None
    source: Source | None = None
    nepal_next: nepal.NextPrice | None = None


def latest(session: Session, asset: AssetDefinition):
    return market_data.latest_quote(session, asset, SOURCES)


def is_live(observed_at: datetime, now: datetime, asset: AssetDefinition) -> bool:
    if asset.calendar.is_open(now):
        return -timedelta(seconds=60) <= now - observed_at <= MAX_AGE  # small clock skew allowed
    return freshness.live_quote(observed_at, now, asset.calendar).status is FreshnessStatus.MARKET_CLOSED


def needs_fetch(observed_at: datetime | None, now: datetime, asset: AssetDefinition) -> bool:
    """Only while the market is open: a closed market's price does not move."""
    return asset.calendar.is_open(now) and (observed_at is None or now - observed_at >= CACHE)


def fetch(asset: AssetDefinition, now: datetime) -> Source | None:
    """Primary, then backup, within FETCH_BUDGET_SECONDS in total. Stores the first quote that passes
    the jump check (through the normal path, with its flags) and returns its source."""
    started = time.monotonic()
    for source, fetch_fn in jobs.SPOT_SOURCES:
        remaining = FETCH_BUDGET_SECONDS - (time.monotonic() - started)
        if remaining < 1:
            break
        try:
            with make_client() as client:
                client.timeout = httpx.Timeout(remaining)
                quote = fetch_fn(client, now=now, asset=asset, attempts=1)
            jobs.save_checked_quote(quote, None, asset)
        except Exception as exc:  # noqa: BLE001 - try the backup; never fail the page
            log.warning("live %s from %s failed: %s", asset.id, source.value, exc)
            continue
        with session_scope() as session:
            row = latest(session, asset)
        if row is not None and row.source == source.value and row.observed_at == quote.observed_at:
            return source
        log.warning("live %s from %s not used: rejected by the jump check", asset.id, source.value)
    return None


def estimate(session: Session, asset: AssetDefinition, price: float, now: datetime) -> nepal.NextPrice | None:
    """Nepal's next price from the live world price: the same inputs and function as the snapshot
    (``nepal.forecast_next``: today's gap carried forward), with the newest stored dollar rate."""
    h1 = analysis._candles(session, Timeframe.H1, asset=asset)
    _, publications, xau_by_end, fx_mid = analysis.nepal_inputs(session, asset, h1)
    lag = analysis.nepal_lag(publications, xau_by_end, fx_mid, price)
    return nepal.forecast_next(lag, now, nepal.hourly_volatility(h1["close"]), asset.calendar.is_open, asset.nepal_price_step)
