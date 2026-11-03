"""XAU/USD spot trading hours: Sunday 18:00 to Friday 17:00 New York time, with a daily
17:00–18:00 break. Exchange holidays are not modelled yet; on those days live data is
reported as stale rather than closed.
"""

from datetime import datetime, time, timedelta

from gold_advisor.domain import NEW_YORK_TZ, UTC

_CLOSE = time(17, 0)
_OPEN = time(18, 0)
_FRIDAY, _SATURDAY, _SUNDAY = 4, 5, 6


def is_xau_open(at: datetime) -> bool:
    ny = at.astimezone(NEW_YORK_TZ)
    day, t = ny.weekday(), ny.time()
    if day == _SATURDAY:
        return False
    if day == _SUNDAY:
        return t >= _OPEN
    if day == _FRIDAY:
        return t < _CLOSE
    return not (_CLOSE <= t < _OPEN)


def last_open_instant(at: datetime) -> datetime:
    """The latest moment at or before ``at`` when the market was open (its close time if closed)."""
    if is_xau_open(at):
        return at
    ny = at.astimezone(NEW_YORK_TZ)
    if ny.weekday() < _FRIDAY or (ny.weekday() == _FRIDAY and ny.time() < _OPEN):
        # Daily break, Monday–Thursday (Friday has no reopening).
        close_day = ny.date()
    else:
        close_day = ny.date() - timedelta(days=(ny.weekday() - _FRIDAY) % 7)
    return datetime.combine(close_day, _CLOSE, tzinfo=NEW_YORK_TZ).astimezone(UTC)
