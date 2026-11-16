"""Upcoming US announcements for the Today page, each with one fixed plain line."""

from dataclasses import dataclass
from datetime import datetime, timedelta

VERSION = "announcements-1"
HORIZON = timedelta(days=30)
SHOWN = 4
# The calendar counts as out of date when its collectors last succeeded longer ago than this.
CALENDAR_JOBS = {"federal_reserve.fomc": timedelta(days=7), "fred.release_calendar": timedelta(days=3)}

PLAIN = {
    "us_cpi": "US inflation report. Higher than expected usually pushes gold down; lower usually lifts it.",
    "us_pce": "US inflation report. Higher than expected usually pushes gold down; lower usually lifts it.",
    "us_jobs": "US jobs report. Strong numbers usually push gold down; weak numbers usually lift it.",
    "fomc_decision": "US interest-rate decision. The biggest scheduled mover; prices can jump either way. The app says WAIT in the day before it.",
}


@dataclass(frozen=True)
class Announcement:
    event_type: str
    title: str
    scheduled_at: datetime
    importance: str
    plain: str


def calendar_stale(last_success: dict[str, datetime | None], now: datetime) -> bool:
    return any(last_success.get(job) is None or now - last_success[job] > limit for job, limit in CALENDAR_JOBS.items())


def upcoming(events: list[tuple[str, str, datetime, str]], now: datetime) -> list[Announcement]:
    """``events``: (event_type, title, scheduled_at, importance), any order."""
    rows = sorted((e for e in events if now < e[2] <= now + HORIZON), key=lambda e: e[2])
    return [Announcement(t, title, at, imp, PLAIN.get(t, "US announcement. Prices can move sharply either way.")) for t, title, at, imp in rows[:SHOWN]]
