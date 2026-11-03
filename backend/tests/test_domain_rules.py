from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from gold_advisor import freshness
from gold_advisor.collectors.types import Candle
from gold_advisor.domain import (
    GRAMS_PER_TOLA,
    GRAMS_PER_TROY_OUNCE,
    NEPAL_TZ,
    TROY_OUNCES_PER_TOLA,
    FreshnessStatus,
    Instrument,
    PriceSide,
    QualityFlag,
    Source,
    Timeframe,
)
from gold_advisor.market import is_xau_open, last_open_instant
from gold_advisor.resample import bucket_start, derive


def utc(*args):
    return datetime(*args, tzinfo=UTC)


def npt(*args):
    return datetime(*args, tzinfo=NEPAL_TZ)


class TestUnits:
    def test_tola_to_troy_ounce_matches_spec_constant(self):
        assert abs(GRAMS_PER_TOLA / GRAMS_PER_TROY_OUNCE - TROY_OUNCES_PER_TOLA) < Decimal("0.00001")

    def test_reference_conversion_per_tola(self):
        # XAU/USD x USD/NPR x 0.375
        assert Decimal("3907.20") * Decimal("151.93") * TROY_OUNCES_PER_TOLA == Decimal("222607.836")


class TestMarketHours:
    @pytest.mark.parametrize(
        ("at", "expected"),
        [
            (utc(2026, 11, 2, 5, 0), True),  # Monday
            (utc(2026, 11, 2, 22, 30), False),  # Monday 17:30 New York (EST): daily break
            (utc(2026, 10, 30, 21, 30), False),  # Friday 17:30 New York (EDT): weekend
            (utc(2026, 10, 31, 12, 0), False),  # Saturday
            (utc(2026, 11, 1, 22, 59), False),  # Sunday 17:59 New York (EST)
            (utc(2026, 11, 1, 23, 0), True),  # Sunday 18:00 New York: open
            (utc(2026, 7, 5, 22, 0), True),  # Sunday 18:00 New York (EDT)
        ],
    )
    def test_is_open(self, at, expected):
        assert is_xau_open(at) is expected

    def test_last_open_instant_over_weekend_is_friday_close(self):
        assert last_open_instant(utc(2026, 10, 31, 12, 0)) == utc(2026, 10, 30, 21, 0)  # 17:00 EDT

    def test_last_open_instant_in_daily_break(self):
        assert last_open_instant(utc(2026, 11, 2, 22, 30)) == utc(2026, 11, 2, 22, 0)  # 17:00 EST


class TestFreshness:
    def test_live_quote_fresh_then_stale_while_open(self):
        now = utc(2026, 11, 2, 5, 0)
        assert freshness.live_quote(now - timedelta(minutes=34), now).status is FreshnessStatus.FRESH
        assert freshness.live_quote(now - timedelta(minutes=36), now).status is FreshnessStatus.STALE

    def test_live_quote_over_weekend_is_market_closed_not_stale(self):
        now = utc(2026, 10, 31, 12, 0)
        assert freshness.live_quote(utc(2026, 10, 30, 20, 59), now).status is FreshnessStatus.MARKET_CLOSED

    def test_live_quote_missing_before_close_is_stale_even_when_closed(self):
        now = utc(2026, 10, 31, 12, 0)
        assert freshness.live_quote(utc(2026, 10, 30, 15, 0), now).status is FreshnessStatus.STALE

    def test_nothing_stored_is_unavailable(self):
        assert freshness.live_quote(None, utc(2026, 11, 2)).status is FreshnessStatus.UNAVAILABLE

    def test_candles_lag(self):
        now = utc(2026, 11, 2, 5, 0)
        assert freshness.candles(Timeframe.H1, utc(2026, 11, 2, 3), now).status is FreshnessStatus.FRESH
        assert freshness.candles(Timeframe.H1, utc(2026, 11, 1, 23), now).status is FreshnessStatus.STALE

    def test_nepal_before_noon_expects_previous_publication_day(self):
        assert freshness.expected_nepal_publication_date(npt(2026, 11, 2, 9, 0)) == date(2026, 11, 1)
        assert freshness.expected_nepal_publication_date(npt(2026, 11, 2, 12, 30)) == date(2026, 11, 2)

    def test_nepal_saturday_has_no_publication(self):
        # Saturday 31 Oct and Sunday-morning both expect Friday 30 Oct.
        assert freshness.expected_nepal_publication_date(npt(2026, 10, 31, 15, 0)) == date(2026, 10, 30)
        assert freshness.expected_nepal_publication_date(npt(2026, 11, 1, 9, 0)) == date(2026, 10, 30)

    def test_nepal_missing_today_after_noon_is_stale(self):
        result = freshness.nepal_publication(date(2026, 11, 1), npt(2026, 11, 2, 13, 0))
        assert result.status is FreshnessStatus.STALE
        assert "holiday" in result.reason

    def test_nrb_yesterday_is_fresh_until_evening(self):
        assert freshness.nrb_rate(date(2026, 11, 1), npt(2026, 11, 2, 10)).status is FreshnessStatus.FRESH
        assert freshness.nrb_rate(date(2026, 11, 1), npt(2026, 11, 2, 19)).status is FreshnessStatus.STALE

    def test_fred_business_day_tolerance(self):
        now = utc(2026, 11, 2, 15)  # Monday
        assert freshness.fred_daily(date(2026, 10, 29), now).status is FreshnessStatus.FRESH  # Thu: 2 bdays
        assert freshness.fred_daily(date(2026, 10, 26), now).status is FreshnessStatus.STALE  # Mon: 5 bdays


def h1(start: datetime, o, h, l, c, volume=Decimal(1)) -> Candle:
    return Candle(
        source=Source.DUKASCOPY,
        instrument=Instrument.XAUUSD,
        timeframe=Timeframe.H1,
        bucket_start=start,
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(l),
        close=Decimal(c),
        volume=volume,
        price_side=PriceSide.BID,
    )


class TestResample:
    def test_bucket_alignment(self):
        assert bucket_start(utc(2026, 11, 2, 7, 15), Timeframe.H4) == utc(2026, 11, 2, 4)
        assert bucket_start(utc(2026, 11, 4, 12), Timeframe.W1) == utc(2026, 11, 1)  # Sunday
        assert bucket_start(utc(2026, 11, 1, 0), Timeframe.W1) == utc(2026, 11, 1)

    def test_h4_from_four_complete_hours(self):
        bars = [
            h1(utc(2026, 11, 2, 4), 10, 12, 9, 11),
            h1(utc(2026, 11, 2, 5), 11, 15, 10, 14),
            h1(utc(2026, 11, 2, 6), 14, 14, 8, 9),
            h1(utc(2026, 11, 2, 7), 9, 10, 9, 10),
        ]
        (bar,) = derive(bars, Timeframe.H4, complete_through=utc(2026, 11, 2, 8))
        assert (bar.open, bar.high, bar.low, bar.close) == (10, 15, 8, 10)
        assert bar.volume == 4 and bar.component_count == 4 and bar.quality_flags == ()

    def test_bucket_not_emitted_until_complete(self):
        bars = [h1(utc(2026, 11, 2, 4), 10, 12, 9, 11), h1(utc(2026, 11, 2, 5), 11, 15, 10, 14)]
        assert derive(bars, Timeframe.H4, complete_through=utc(2026, 11, 2, 6)) == []

    def test_session_gap_gives_partial_flag_and_null_volume_propagates(self):
        bars = [h1(utc(2026, 11, 2, 20), 10, 12, 9, 11), h1(utc(2026, 11, 2, 21), 11, 13, 10, 12, volume=None)]
        (bar,) = derive(bars, Timeframe.H4, complete_through=utc(2026, 11, 3))
        assert bar.quality_flags == (QualityFlag.PARTIAL_BUCKET,)
        assert bar.volume is None

    def test_rejects_wrong_underlying_timeframe(self):
        bar = h1(utc(2026, 11, 2, 4), 10, 12, 9, 11)
        with pytest.raises(ValueError):
            derive([bar], Timeframe.W1, complete_through=utc(2026, 11, 9))
