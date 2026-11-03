"""Publication-aware freshness rules. Pure functions: callers pass ``now``.

Cached observations may be displayed with their age, but only FRESH qualifies as current
evidence for downstream analysis.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from gold_advisor.domain import NEPAL_TZ, NEW_YORK_TZ, FreshnessStatus, Timeframe
from gold_advisor.assets import METALS_CALENDAR, MarketCalendar
from gold_advisor.market import is_xau_open, last_open_instant

# Scheduled cloud runs collect every 30 minutes (GitHub Actions can start a few minutes late).
LIVE_QUOTE_MAX_AGE = timedelta(minutes=35)
# Dukascopy history typically lags real time; allow that before calling bars stale.
CANDLE_MAX_LAG: dict[Timeframe, timedelta] = {
    Timeframe.M15: timedelta(hours=1),
    Timeframe.H1: timedelta(hours=3),
    Timeframe.H4: timedelta(hours=9),
    Timeframe.D1: timedelta(days=1, hours=6),
    Timeframe.W1: timedelta(days=8),
}
# FENEGOSIDA usually publishes 10:00–11:00 NPT, Sunday–Friday.
NEPAL_PUBLICATION_DUE = time(12, 0)
NEPAL_NO_PUBLICATION_WEEKDAY = 5  # Saturday
# NRB usually publishes just after midnight NPT, occasionally late in the day.
NRB_LATE_PUBLICATION_CUTOFF = time(18, 0)
FRED_MAX_BUSINESS_DAYS_BEHIND = 3


@dataclass(frozen=True)
class Freshness:
    status: FreshnessStatus
    reason: str
    age_seconds: float | None = None


def _unavailable() -> Freshness:
    return Freshness(FreshnessStatus.UNAVAILABLE, "no verified observation stored")


def live_quote(observed_at: datetime | None, now: datetime, calendar: MarketCalendar = METALS_CALENDAR) -> Freshness:
    if observed_at is None:
        return _unavailable()
    age = (now - observed_at).total_seconds()
    if calendar.is_open(now):
        if now - observed_at <= LIVE_QUOTE_MAX_AGE:
            return Freshness(FreshnessStatus.FRESH, "quote within 35 minutes", age)
        return Freshness(FreshnessStatus.STALE, "quote older than 35 minutes while market is open", age)
    if observed_at >= calendar.last_open(now) - LIVE_QUOTE_MAX_AGE:
        return Freshness(FreshnessStatus.MARKET_CLOSED, "market closed; last quote is from the close", age)
    return Freshness(FreshnessStatus.STALE, "market closed, but last quote predates the close", age)


def candles(timeframe: Timeframe, latest_bucket_start: datetime | None, now: datetime, calendar: MarketCalendar = METALS_CALENDAR) -> Freshness:
    if latest_bucket_start is None:
        return _unavailable()
    bar_end = latest_bucket_start + timeframe.duration
    age = (now - bar_end).total_seconds()
    reference = now if calendar.is_open(now) else calendar.last_open(now)
    if bar_end >= reference - CANDLE_MAX_LAG[timeframe]:
        if calendar.is_open(now):
            return Freshness(FreshnessStatus.FRESH, f"latest {timeframe} bar within expected lag", age)
        return Freshness(FreshnessStatus.MARKET_CLOSED, f"market closed; latest {timeframe} bar covers the close", age)
    return Freshness(FreshnessStatus.STALE, f"latest {timeframe} bar is behind the expected lag", age)


def _previous_nepal_publication_day(d: date) -> date:
    d -= timedelta(days=1)
    while d.weekday() == NEPAL_NO_PUBLICATION_WEEKDAY:
        d -= timedelta(days=1)
    return d


def expected_nepal_publication_date(now: datetime) -> date:
    local = now.astimezone(NEPAL_TZ)
    today = local.date()
    if today.weekday() != NEPAL_NO_PUBLICATION_WEEKDAY and local.time() >= NEPAL_PUBLICATION_DUE:
        return today
    return _previous_nepal_publication_day(today)


def nepal_publication(latest_rate_date: date | None, now: datetime) -> Freshness:
    if latest_rate_date is None:
        return _unavailable()
    expected = expected_nepal_publication_date(now)
    days_behind = (expected - latest_rate_date).days
    if latest_rate_date >= expected:
        return Freshness(FreshnessStatus.FRESH, f"publication for {latest_rate_date} is current")
    return Freshness(
        FreshnessStatus.STALE,
        f"expected publication for {expected}, latest is {latest_rate_date} ({days_behind} days behind;"
        " may be a public holiday)",
    )


def nrb_rate(latest_rate_date: date | None, now: datetime) -> Freshness:
    if latest_rate_date is None:
        return _unavailable()
    local = now.astimezone(NEPAL_TZ)
    today = local.date()
    if latest_rate_date >= today:
        return Freshness(FreshnessStatus.FRESH, "today's NRB rate is published")
    if latest_rate_date == today - timedelta(days=1) and local.time() < NRB_LATE_PUBLICATION_CUTOFF:
        return Freshness(FreshnessStatus.FRESH, "yesterday's NRB rate; today's not yet due")
    return Freshness(FreshnessStatus.STALE, f"latest NRB rate is for {latest_rate_date}")


def _business_days_between(start: date, end: date) -> int:
    days, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            days += 1
    return days


def fred_daily(latest_obs_date: date | None, now: datetime) -> Freshness:
    if latest_obs_date is None:
        return _unavailable()
    behind = _business_days_between(latest_obs_date, now.astimezone(NEW_YORK_TZ).date())
    if behind <= FRED_MAX_BUSINESS_DAYS_BEHIND:
        return Freshness(FreshnessStatus.FRESH, f"{behind} US business days behind")
    return Freshness(FreshnessStatus.STALE, f"{behind} US business days behind (limit {FRED_MAX_BUSINESS_DAYS_BEHIND})")
