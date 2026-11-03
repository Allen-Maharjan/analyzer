"""Nepal price versus the international reference.

Reference per tola = XAU/USD × USD/NPR (NRB buy/sell midpoint) × 0.375. This is a
comparison benchmark, not a dealer quote or a tax model. The premium is how far the
FENEGOSIDA hallmark price sits above that reference.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd

from gold_advisor.domain import NEPAL_TZ, TROY_OUNCES_PER_TOLA, UTC

VERSION = "nepal-3"
PREMIUM_WINDOW = 20
PREMIUM_MIN_OBSERVATIONS = 10
# "Recent high" for the drop-from-high check: the highest of the last 20 publications (about 3–4 weeks).
RECENT_HIGH_WINDOW = 20
# Used when a publication has a date but no time. Typical publication is 10:00–11:00 NPT.
ASSUMED_PUBLICATION_TIME = time(10, 45)
LAG_MIN_GAP = 0.01
# Next-price forecast. A two-year test (Nov 2024 to Nov 2026) found FENEGOSIDA follows the world
# price of about 9:45 am Nepal time, and that carrying today's gap over world prices forward
# (today's Nepal price x world move x dollar move) beats the average gap: mean error 0.29% vs
# 0.42% for gold, 0.43% vs 0.61% for silver, when the 9:45 world price is known.
NEXT_PUBLICATION_TIME = time(10, 45)  # typical; used to count hours until the next price
NO_PUBLICATION_WEEKDAY = 5  # Saturday
LIKELY_RANGE_Z = 1.05  # calibrated: z=1.28 put 86-92% of real prices inside the "80%" range in the backtest
PREMIUM_CHANGE_WINDOW = 60
DEFAULT_PREMIUM_CHANGE = 0.004
LAG_STD_MULTIPLE = 1.5
OUNCES_PER_TOLA = float(TROY_OUNCES_PER_TOLA)


@dataclass(frozen=True)
class Publication:
    rate_date: date
    published_at: datetime | None
    price: float


@dataclass(frozen=True)
class AlignedPublication:
    rate_date: date
    at: datetime
    time_known: bool
    nepal_price: float
    xau_usd: float
    usd_npr: float
    reference: float
    premium: float


@dataclass(frozen=True)
class NepalLag:
    latest: AlignedPublication | None
    premium_mean: float | None
    premium_std: float | None
    premium_observations: int
    reference_now: float | None
    implied_nepal_now: float | None
    expected_adjustment_pct: float | None  # implied Nepal price vs latest published, e.g. -0.02
    adjustment_pending: bool | None
    intl_change_since_publication_pct: float | None
    nepal_change_3_publications: float | None  # rupees, latest minus two publications earlier
    nepal_change_3_publications_pct: float | None
    publication_dates_only: bool
    recent_high: float | None = None  # highest of the last RECENT_HIGH_WINDOW publications
    drawdown_from_high_pct: float | None = None  # latest vs that high, e.g. -0.06
    premium_day_change_p80: float | None = None  # 80th percentile of |gap change| between publications


@dataclass(frozen=True)
class NextPrice:
    """Nepal's expected price at its next publication, with an 80% likely range."""

    publish_at: datetime  # expected publication time (UTC)
    estimate: float
    low: float
    high: float
    hours_ahead: float
    market_hours_ahead: float  # hours the world market is open before then; only these move the price
    change_pct: float  # expected change vs the latest published price (unrounded)
    basis: str


def publication_instant(p: Publication) -> tuple[datetime, bool]:
    if p.published_at is not None:
        return p.published_at.astimezone(UTC), True
    return datetime.combine(p.rate_date, ASSUMED_PUBLICATION_TIME, tzinfo=NEPAL_TZ).astimezone(UTC), False


def _asof(series: pd.Series, at: datetime) -> float | None:
    s = series[series.index <= at]
    return float(s.iloc[-1]) if len(s) else None


def align(publications: list[Publication], xau_close_by_end: pd.Series, fx_mid_by_date: pd.Series) -> list[AlignedPublication]:
    """``xau_close_by_end`` is indexed by bar end time, so only closed bars are visible."""
    out = []
    for p in publications:
        at, known = publication_instant(p)
        xau = _asof(xau_close_by_end, at)
        fx = _asof(fx_mid_by_date, pd.Timestamp(p.rate_date))
        if xau is None or fx is None:
            continue
        reference = xau * fx * OUNCES_PER_TOLA
        out.append(AlignedPublication(p.rate_date, at, known, p.price, xau, fx, reference, p.price / reference - 1))
    return out


def analyse(
    publications: list[Publication],
    xau_close_by_end: pd.Series,
    fx_mid_by_date: pd.Series,
    xau_now: float | None,
) -> NepalLag:
    aligned = align(sorted(publications, key=lambda p: p.rate_date), xau_close_by_end, fx_mid_by_date)
    latest = aligned[-1] if aligned else None
    window = [a.premium for a in aligned[-PREMIUM_WINDOW - 1 : -1]]  # prior publications only
    enough = len(window) >= PREMIUM_MIN_OBSERVATIONS
    mean = float(np.mean(window)) if enough else None
    std = float(np.std(window, ddof=1)) if enough else None

    reference_now = implied = adjustment = None
    pending = None
    if latest is not None and xau_now is not None:
        fx_now = float(fx_mid_by_date.iloc[-1])
        reference_now = xau_now * fx_now * OUNCES_PER_TOLA
        if mean is not None:
            implied = reference_now * (1 + mean)
            adjustment = implied / latest.nepal_price - 1
            threshold = max(LAG_MIN_GAP, LAG_STD_MULTIPLE * (std or 0))
            pending = abs(adjustment) > threshold

    changes = np.abs(np.diff([a.premium for a in aligned[-PREMIUM_CHANGE_WINDOW - 1 :]]))
    premium_change = float(np.percentile(changes, 80)) if len(changes) >= PREMIUM_MIN_OBSERVATIONS else None

    prices = [p.price for p in sorted(publications, key=lambda p: p.rate_date)]
    change = pct = None
    if len(prices) >= 3:
        change = prices[-1] - prices[-3]
        pct = change / prices[-3]
    high = drawdown = None
    if len(prices) >= RECENT_HIGH_WINDOW:
        high = max(prices[-RECENT_HIGH_WINDOW:])
        drawdown = prices[-1] / high - 1

    return NepalLag(
        latest=latest,
        premium_mean=mean,
        premium_std=std,
        premium_observations=len(window),
        reference_now=reference_now,
        implied_nepal_now=implied,
        expected_adjustment_pct=adjustment,
        adjustment_pending=pending,
        intl_change_since_publication_pct=(xau_now / latest.xau_usd - 1) if latest and xau_now else None,
        nepal_change_3_publications=change,
        nepal_change_3_publications_pct=pct,
        publication_dates_only=bool(latest and not latest.time_known),
        recent_high=high,
        drawdown_from_high_pct=drawdown,
        premium_day_change_p80=premium_change,
    )


def next_publication_at(now: datetime, latest_rate_date: date | None) -> datetime:
    """When Nepal's next price is expected: today at about 10:45 if today's isn't out yet, else the
    next day. No publication on Saturday. A late publication counts as due now."""
    local = now.astimezone(NEPAL_TZ)
    day = local.date()
    if latest_rate_date is not None and latest_rate_date >= day:
        day += timedelta(days=1)
    while day.weekday() == NO_PUBLICATION_WEEKDAY:
        day += timedelta(days=1)
    due = datetime.combine(day, NEXT_PUBLICATION_TIME, tzinfo=NEPAL_TZ).astimezone(UTC)
    return max(due, now.astimezone(UTC))


def forecast_next(
    lag: NepalLag,
    now: datetime,
    hourly_vol: float | None,
    is_open: Callable[[datetime], bool],
    step: float = 1.0,
) -> NextPrice | None:
    """Carry today's gap forward to the current world price; widen the range with the world-market
    hours left before publication (world volatility) plus the usual day-to-day change in the gap."""
    if lag.latest is None or lag.reference_now is None:
        return None
    publish_at = next_publication_at(now, lag.latest.rate_date)
    hours = (publish_at - now).total_seconds() / 3600
    open_hours = sum(1 for h in range(int(math.ceil(hours))) if is_open(now + timedelta(hours=h)))
    estimate = lag.reference_now * (1 + lag.latest.premium)
    gap_noise = lag.premium_day_change_p80 if lag.premium_day_change_p80 is not None else DEFAULT_PREMIUM_CHANGE
    world_noise = LIKELY_RANGE_Z * (hourly_vol or 0.0) * math.sqrt(open_hours)
    half = math.sqrt(gap_noise**2 + world_noise**2)

    def snap(value: float) -> float:
        return round(value / step) * step

    return NextPrice(
        publish_at=publish_at,
        estimate=snap(estimate),
        low=snap(estimate * (1 - half)),
        high=snap(estimate * (1 + half)),
        hours_ahead=round(hours, 1),
        market_hours_ahead=float(open_hours),
        change_pct=estimate / lag.latest.nepal_price - 1,
        basis="today's Nepal price carried forward by the world price and dollar rate since it was set",
    )


def to_float(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)
