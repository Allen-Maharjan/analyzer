from datetime import date, datetime

from gold_advisor.analytics import track_record as tr
from gold_advisor.domain import NEPAL_TZ, UTC, Decision


def npt(day: int, hour: int, minute: int = 0, month: int = 11) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=NEPAL_TZ).astimezone(UTC)


def snap(at: datetime, latest: date, estimate: float | None = None, decision: Decision = Decision.WAIT) -> tr.Snapshot:
    return tr.Snapshot(at, latest, estimate, estimate and estimate - 1000, estimate and estimate + 1000, decision, "rule")


def test_normal_day_pairs_the_last_snapshot_before_publication():
    pubs = [tr.Publication(date(2026, 11, 13), npt(13, 10, 38), 271700)]
    snaps = [
        snap(npt(12, 20), date(2026, 11, 9), 270000),
        snap(npt(13, 9), date(2026, 11, 9), 270800),
        snap(npt(13, 11), date(2026, 11, 13), 999999),  # after publication: ignored
    ]
    [row] = tr.forecast_rows(pubs, snaps)
    assert (row.estimate, row.actual, row.error_npr, row.inside_range) == (270800, 271700, 900, True)
    assert row.hours_before == 1.6
    summary = tr.forecast_summary([row])
    assert summary.count == 1 and summary.small_sample and round(summary.mean_abs_error_npr) == 900


def test_day_without_an_earlier_snapshot_is_left_out():
    pubs = [tr.Publication(date(2026, 11, 13), npt(13, 10, 38), 271700)]
    assert tr.forecast_rows(pubs, [snap(npt(13, 9), date(2026, 11, 13), 270800)]) == []  # already knew D's price
    assert tr.forecast_rows(pubs, [snap(npt(12, 9), date(2026, 11, 9), None)]) == []  # no forecast stored


def test_unknown_publication_time_uses_10_45():
    pubs = [tr.Publication(date(2026, 11, 13), None, 271700)]
    snaps = [snap(npt(13, 10, 30), date(2026, 11, 9), 271000), snap(npt(13, 10, 50), date(2026, 11, 9), 260000)]
    [row] = tr.forecast_rows(pubs, snaps)
    assert row.estimate == 271000 and row.hours_before == 0.2


def test_advice_with_fewer_than_five_later_publications_is_still_open():
    days = [date(2026, 11, d) for d in (2, 3, 4, 5, 6, 8, 9)]
    prices = [280000, 279000, 281000, 278000, 282000, 283000, 284000]
    pubs = [tr.Publication(d, None, p) for d, p in zip(days, prices)]
    snaps = [snap(npt(d.day, 11, 30), d, None, Decision.WAIT) for d in days]
    rows = {r.rate_date: r for r in tr.advice_rows(pubs, snaps)}
    first = rows[date(2026, 11, 2)]
    assert not first.open and first.outcome == "price fell Rs 2,000 within 5 updates" and first.good is True
    later = rows[date(2026, 11, 4)]
    assert later.open and later.outcome == "still open" and later.later_count == 4
    assert tr.advice_summary(list(rows.values())).status == "insufficient"
