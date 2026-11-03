from datetime import UTC, date, datetime

from gold_advisor.decision.nepal import AlignedPublication, NepalLag, forecast_next, next_publication_at


def lag(**overrides) -> NepalLag:
    latest = AlignedPublication(date(2026, 11, 3), datetime(2026, 11, 3, 5, tzinfo=UTC), True, 275000, 3900, 151.9, 222000, 0.2387)
    base = dict(latest=latest, premium_mean=0.22, premium_std=0.006, premium_observations=20, reference_now=220000,
                implied_nepal_now=268400, expected_adjustment_pct=-0.024, adjustment_pending=True, intl_change_since_publication_pct=-0.009,
                nepal_change_3_publications=0.0, nepal_change_3_publications_pct=0.0, publication_dates_only=False, premium_day_change_p80=0.004)
    return NepalLag(**{**base, **overrides})


def test_next_publication_skips_saturday_and_today_once_published():
    # Tue 3 Nov 2026, 14:00 NPT, today's price already out -> Wed 10:45 NPT (05:00 UTC).
    assert next_publication_at(datetime(2026, 11, 3, 8, 15, tzinfo=UTC), date(2026, 11, 3)) == datetime(2026, 11, 4, 5, 0, tzinfo=UTC)
    # Fri 6 Nov afternoon -> Sunday 8 Nov (no Saturday publication).
    assert next_publication_at(datetime(2026, 11, 6, 9, 0, tzinfo=UTC), date(2026, 11, 6)).date() == date(2026, 11, 8)
    # Wed 4 Nov 08:00 NPT, today's not out yet -> today 10:45.
    assert next_publication_at(datetime(2026, 11, 4, 2, 15, tzinfo=UTC), date(2026, 11, 3)) == datetime(2026, 11, 4, 5, 0, tzinfo=UTC)


def test_forecast_carries_todays_gap_forward_and_rounds_like_fenegosida():
    f = forecast_next(lag(), datetime(2026, 11, 3, 8, 15, tzinfo=UTC), 0.002, lambda t: True, step=100)
    # 220000 x 1.2387 = 272514 -> Rs 2,72,500; not the usual-gap figure (268400).
    assert f.estimate == 272500 and f.estimate % 100 == 0
    assert f.low < f.estimate < f.high
    assert round(f.change_pct, 4) == round(220000 * 1.2387 / 275000 - 1, 4)


def test_range_widens_with_more_market_hours_left():
    now = datetime(2026, 11, 3, 8, 15, tzinfo=UTC)
    near = forecast_next(lag(), now, 0.002, lambda t: False, step=1)  # market closed: gap noise only
    far = forecast_next(lag(), now, 0.002, lambda t: True, step=1)
    assert (near.high - near.low) < (far.high - far.low)
