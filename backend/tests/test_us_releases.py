from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from gold_advisor.collectors import us_releases
from gold_advisor.collectors.types import SourceSchemaError

FIXTURE = (Path(__file__).parent / "fixtures" / "fred_calendar_cpi_2026.html").read_text()
CPI = us_releases.RELEASES[0]


def test_parses_every_cpi_date_with_the_new_york_830_release_time():
    events = us_releases.parse(FIXTURE, CPI)
    assert len(events) == 12
    first = events[0]
    # 7:30 am Central on 13 Jan 2026 = 8:30 am New York = 13:30 UTC.
    assert first.scheduled_at == datetime(2026, 1, 13, 13, 30, tzinfo=UTC)
    assert first.event_type == "us_cpi" and first.importance == "high"  # a risk, not a WAIT trigger
    assert {e.scheduled_at.date() for e in events} >= {date(2026, 11, 10), date(2026, 12, 10)}
    # Summer time: 14 Jul 2026 7:30 am CDT = 12:30 UTC.
    assert datetime(2026, 7, 14, 12, 30, tzinfo=UTC) in {e.scheduled_at for e in events}


def test_rows_for_other_releases_are_ignored():
    assert us_releases.parse(FIXTURE, us_releases.RELEASES[1]) == []


def test_empty_current_year_is_a_schema_error():
    class Client:
        pass

    def fake_get(client, url, params):
        return type("R", (), {"text": "<html></html>"})()

    original = us_releases.get_with_retries
    us_releases.get_with_retries = fake_get
    try:
        with pytest.raises(SourceSchemaError):
            us_releases.fetch(Client(), date(2026, 11, 3))
    finally:
        us_releases.get_with_retries = original
