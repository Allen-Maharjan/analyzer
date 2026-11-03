"""US data releases that move gold sharply: inflation (CPI), jobs (NFP) and PCE inflation.

Dates and times come from FRED's public release calendar (no API key), which lists the whole
year ahead, including future dates. Times on that page are US Central time. All three are
released at 8:30 am New York time.

Saved with importance "high": shown as upcoming announcements and listed as a risk, but they do
not force WAIT. A walk-forward test (2025-2026) found that waiting around them did not improve
BUY timing. Only FOMC decisions ("major") force WAIT.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

from gold_advisor.collectors.fomc import ScheduledEvent
from gold_advisor.collectors.http import get_with_retries
from gold_advisor.collectors.types import SourceSchemaError
from gold_advisor.domain import UTC, Source

URL = "https://fred.stlouisfed.org/releases/calendar"
# FRED's calendar pages are large (~70 KB) and sometimes slow from GitHub's runners; the default
# 20 s timed out there. Next year's schedule is usually published in the autumn, so it is only
# fetched from September.
PAGE_TIMEOUT = 60.0
NEXT_YEAR_FROM_MONTH = 9


@dataclass(frozen=True)
class Release:
    rid: int
    event_type: str
    title: str


RELEASES = (
    Release(10, "us_cpi", "US inflation report (CPI)"),
    Release(50, "us_jobs", "US jobs report (NFP)"),
    Release(54, "us_pce", "US PCE inflation report"),
)

CENTRAL_TZ = ZoneInfo("America/Chicago")

_TOKEN = re.compile(
    r'font-weight: bold;">\s*(?:[A-Z][a-z]+day)\s+(?P<month>[A-Z][a-z]+)\s+(?P<day>\d{1,2}),\s+(?P<year>\d{4})\s*</span>'
    r"|>\s*(?P<time>\d{1,2}:\d{2}\s*[ap]m)\s*</td>"
    r'|href="/release\?rid=(?P<rid>\d+)"'
)
_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November",
     "December"], start=1)}


def parse(html: str, release: Release) -> list[ScheduledEvent]:
    """One event per calendar row for ``release``. The page lists a date header, then a time cell,
    then the release link."""
    events: list[ScheduledEvent] = []
    day: date | None = None
    clock: str | None = None
    for m in _TOKEN.finditer(html):
        if m["month"]:
            month = _MONTHS.get(m["month"])
            if month is None:
                raise SourceSchemaError(f"fred calendar: unknown month {m['month']!r}")
            day, clock = date(int(m["year"]), month, int(m["day"])), None
        elif m["time"]:
            clock = m["time"].replace(" ", "")
        elif m["rid"] and day is not None and clock is not None and int(m["rid"]) == release.rid:
            local = datetime.strptime(f"{day.isoformat()} {clock}", "%Y-%m-%d %I:%M%p").replace(tzinfo=CENTRAL_TZ)
            events.append(
                ScheduledEvent(
                    source=Source.FRED,
                    event_type=release.event_type,
                    scheduled_at=local.astimezone(UTC),
                    title=release.title,
                    importance="high",
                    source_url=f"{URL}?rid={release.rid}",
                )
            )
            clock = None
    return sorted(set(events), key=lambda e: e.scheduled_at)


def fetch(client: httpx.Client, today: date) -> list[ScheduledEvent]:
    """This year's and next year's dates. Next year's page is often empty until autumn; that is fine.
    An empty page for the current year means the layout changed."""
    events: list[ScheduledEvent] = []
    for release in RELEASES:
        years = (today.year, today.year + 1) if today.month >= NEXT_YEAR_FROM_MONTH else (today.year,)
        for year in years:
            html = get_with_retries(client, URL, params={"rid": release.rid, "y": year, "view": "year"}, timeout=PAGE_TIMEOUT).text
            found = parse(html, release)
            if year == today.year and not found:
                raise SourceSchemaError(f"fred calendar: no {release.event_type} dates for {year}; page layout may have changed")
            events.extend(found)
    return events
