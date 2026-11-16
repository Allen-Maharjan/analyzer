"""Buying in two parts (owner-approved in principle 2026-11-16; never more than two parts).

When the advice is BUY but world prices are falling (bearish outlook, or a breakdown whose fall has
only paused), the advice becomes "buy half now", with three plain triggers for the second half:

- dip: Nepal's price drops to about the nearest floor (``analytics.position.key_levels``);
- recovery: it rises past about the nearest ceiling, a sign the fall is probably over;
- deadline: the day before the next major or high-importance US announcement within 14 days,
  otherwise 7 days from today.

Whichever comes first. With a neutral or bullish outlook the advice stays "buy the whole amount".
WAIT and WATCH CLOSELY are unchanged. Pure functions.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

from gold_advisor.domain import NEPAL_TZ, Decision, Outlook

VERSION = "split-1"
# Off: the two-year replay (2026-11-16, backtest.compare_split) found one purchase cheaper for both
# metals. Gold: two-part paid Rs 624 per tola more on the 33 weeks it applied (cheaper in 16);
# silver: Rs 23 more on 25 weeks (cheaper in 10). See docs/ROADMAP.md. Turn on only with the owner.
ENABLED = False
EVENT_HORIZON = timedelta(days=14)
DEFAULT_DEADLINE_DAYS = 7


@dataclass(frozen=True)
class Split:
    reason: str
    dip_npr: float | None
    recovery_npr: float | None
    deadline: date
    deadline_reason: str


@dataclass(frozen=True)
class SecondHalf:
    """State of the second half after the owner recorded the first."""

    first_part_at: datetime
    first_part_price: float | None
    dip_npr: float | None
    recovery_npr: float | None
    deadline: date | None
    reached: str | None  # "dip" | "recovery" | "deadline" | None
    plain: str


def applies(decision: Decision, outlook: Outlook | None, paused_breakdown: bool) -> str | None:
    """The reason to split, or None to buy the whole amount (always None while ENABLED is off)."""
    return reason_for(decision, outlook, paused_breakdown) if ENABLED else None


def reason_for(decision: Decision, outlook: Outlook | None, paused_breakdown: bool) -> str | None:
    """The split condition itself, ignoring ENABLED (the backtest compares both ways)."""
    if decision is not Decision.BUY:
        return None
    if outlook is Outlook.BEARISH:
        return "World prices are generally falling right now."
    if paused_breakdown:
        return "World prices recently broke below an important floor; the fall has paused but could resume."
    return None


def deadline(now: datetime, events: list[tuple[datetime, str]]) -> tuple[date, str]:
    """``events``: (scheduled_at, title) of major or high-importance announcements, any order."""
    today = now.astimezone(NEPAL_TZ).date()
    upcoming = sorted((at, title) for at, title in events if now < at <= now + EVENT_HORIZON)
    for at, title in upcoming:
        day_before = at.astimezone(NEPAL_TZ).date() - timedelta(days=1)
        if day_before > today:
            return day_before, f"the day before the {title}"
    return today + timedelta(days=DEFAULT_DEADLINE_DAYS), "a week from today"


def plan(reason: str, floors_npr: list[float], ceilings_npr: list[float], nepal_price: float | None, now: datetime,
         events: list[tuple[datetime, str]]) -> Split:
    """``floors_npr`` and ``ceilings_npr`` nearest first. The dip trigger is the nearest floor below
    Nepal's current price and the recovery trigger the nearest ceiling above it, so neither is met
    at once."""
    below = [f for f in floors_npr if nepal_price is None or f < nepal_price]
    above = [c for c in ceilings_npr if nepal_price is None or c > nepal_price]
    day, why = deadline(now, events)
    return Split(reason=reason, dip_npr=below[0] if below else None, recovery_npr=above[0] if above else None,
                 deadline=day, deadline_reason=why)


def triggers_plain(dip: float | None, recovery: float | None, deadline_day: date | None) -> list[str]:
    from gold_advisor.decision.rules import rupees

    out = []
    if dip is not None:
        out.append(f"If Nepal's price drops to about {rupees(dip)}, buy the second half.")
    if recovery is not None:
        out.append(f"If it rises past about {rupees(recovery)}, the fall is probably over: buy the second half.")
    if deadline_day is not None:
        out.append(f"Otherwise buy it on {deadline_day:%a} {deadline_day.day} {deadline_day:%b} at the latest.")
    return out


def second_half(first_part_at: datetime, first_part_price: float | None, dip: float | None, recovery: float | None,
                deadline_day: date | None, nepal_price: float | None, now: datetime) -> SecondHalf:
    from gold_advisor.decision.rules import rupees

    today = now.astimezone(NEPAL_TZ).date()
    reached = None
    if nepal_price is not None and dip is not None and nepal_price <= dip:
        reached, plain = "dip", f"Nepal's price has dropped to {rupees(nepal_price)}. Time to buy the second half."
    elif nepal_price is not None and recovery is not None and nepal_price >= recovery:
        reached, plain = "recovery", f"Nepal's price has risen to {rupees(nepal_price)}; the fall looks over. Time to buy the second half."
    elif deadline_day is not None and today >= deadline_day:
        reached, plain = "deadline", "The last day for the second half has come. Time to buy it."
    else:
        plain = "Waiting for the second half. " + " ".join(triggers_plain(dip, recovery, deadline_day))
    return SecondHalf(first_part_at, first_part_price, dip, recovery, deadline_day, reached, plain)
