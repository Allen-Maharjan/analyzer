"""FOMC meeting calendar from the Federal Reserve's public page.

Each scheduled meeting becomes one event at the statement release time: 14:00 New York on
the meeting's last day. Notation votes and unscheduled meetings are skipped.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, time

import httpx

from gold_advisor.collectors.http import get_with_retries
from gold_advisor.collectors.types import SourceSchemaError
from gold_advisor.domain import NEW_YORK_TZ, UTC, Source

URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
STATEMENT_TIME = time(14, 0)
EVENT_TYPE = "fomc_decision"

_TOKEN = re.compile(
    r'<h4><a id="\d+">(?P<year>\d{4}) FOMC Meetings</a></h4>'
    r'|fomc-meeting__month[^>]*><strong>(?P<month>[^<]+)</strong>'
    r'|fomc-meeting__date[^>]*>(?P<dates>[^<]+)<'
)
_DATES = re.compile(r"^(?P<first>\d{1,2})(?:-(?P<last>\d{1,2}))?\*?$")
_MONTHS = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"], start=1)}
_MONTH_ABBR = {k[:3]: v for k, v in _MONTHS.items()}


@dataclass(frozen=True)
class ScheduledEvent:
    source: Source
    event_type: str
    scheduled_at: datetime
    title: str
    importance: str
    source_url: str


def _month_number(name: str) -> int:
    key = name.strip().lower()
    if key in _MONTHS:
        return _MONTHS[key]
    if key[:3] in _MONTH_ABBR:
        return _MONTH_ABBR[key[:3]]
    raise SourceSchemaError(f"fomc: unknown month {name!r}")


def parse(html: str) -> list[ScheduledEvent]:
    events: list[ScheduledEvent] = []
    year: int | None = None
    month_label: str | None = None
    for m in _TOKEN.finditer(html):
        if m["year"]:
            year, month_label = int(m["year"]), None
        elif m["month"]:
            month_label = m["month"]
        elif m["dates"] and year and month_label:
            match = _DATES.match(m["dates"].strip())
            if match is None:
                continue  # notation vote, unscheduled meeting, or other annotation
            first, last = int(match["first"]), int(match["last"] or match["first"])
            months = [_month_number(part) for part in month_label.split("/")]
            end_month = months[-1] if last < first else months[0]
            meeting_end = date(year, end_month, last)
            scheduled = datetime.combine(meeting_end, STATEMENT_TIME, tzinfo=NEW_YORK_TZ).astimezone(UTC)
            events.append(
                ScheduledEvent(
                    source=Source.FEDERAL_RESERVE,
                    event_type=EVENT_TYPE,
                    scheduled_at=scheduled,
                    title=f"FOMC rate decision ({month_label.strip()} {year})",
                    importance="major",
                    source_url=URL,
                )
            )
    if not events:
        raise SourceSchemaError("fomc: no meetings found; page layout may have changed")
    return events


def fetch(client: httpx.Client) -> list[ScheduledEvent]:
    return parse(get_with_retries(client, URL).text)
