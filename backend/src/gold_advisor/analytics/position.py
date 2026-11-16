"""Where the price stands, and the nearest floors and ceilings in rupees. Pure functions.

``position``: Nepal's price against the lowest and highest of its last 30 publications, and the world
price against its 52-week range, with one plain sentence.

``key_levels``: the two nearest supports below and the two nearest resistances above the world
price, taken from the 1D levels first, then 4h, then 1W, skipping any within 0.3% of one already
chosen. Each carries its rupee value: world price x ``rupees_per_usd_oz`` (the snapshot's factor),
rounded to the asset's step. The rupee value moves with the dollar rate and Nepal's gap, so it is
always shown as "about".
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd

VERSION = "position-1"
NEPAL_WINDOW = 30
YEAR = timedelta(days=365)
LEVEL_TIMEFRAMES = ("1D", "4h", "1W")
LEVEL_MIN_GAP = 0.003
LEVELS_PER_SIDE = 2
RECENT_LOW_DAYS = 30  # mention "made its lowest price of the past year N days ago" only within this


@dataclass(frozen=True)
class Position:
    nepal_price: float | None
    nepal_low: float | None
    nepal_low_date: date | None
    nepal_high: float | None
    nepal_high_date: date | None
    nepal_window_start: date | None
    nepal_publications: int
    above_low_npr: float | None
    below_high_npr: float | None
    world_price: float | None
    world_52w_low: float | None
    world_52w_high: float | None
    days_since_52w_low: int | None  # completed daily bars since the bar that set the 52-week low
    plain: str | None


@dataclass(frozen=True)
class KeyLevel:
    kind: str  # "floor" (support below) | "ceiling" (resistance above)
    timeframe: str
    world_price: float
    rupees: float | None
    touches: int
    manual: bool
    state: str  # from level_states, "none" when quiet


def _short(d: date) -> str:
    return f"{d.day} {d:%b}"


def _rupees(value: float) -> str:
    from gold_advisor.decision.rules import rupees

    return rupees(value)


def position(label: str, nepal_history: list[tuple[date, float]], d1: pd.DataFrame, world_now: float | None, now: datetime) -> Position:
    """``nepal_history`` oldest first; ``d1`` completed daily bars (open/high/low/close) indexed by UTC start."""
    window = nepal_history[-NEPAL_WINDOW:]
    nepal_price = window[-1][1] if window else None
    low = min(window, key=lambda x: (x[1], -x[0].toordinal())) if window else None  # latest date of the low
    high = max(window, key=lambda x: (x[1], x[0].toordinal())) if window else None

    completed = d1[d1.index + timedelta(days=1) <= now] if len(d1) else d1
    year = completed[completed.index >= completed.index[-1] - YEAR] if len(completed) else completed
    w_low = float(year["low"].min()) if len(year) else None
    w_high = float(year["high"].max()) if len(year) else None
    days_since = None
    if len(year):
        lows = completed["low"]
        last_new_low = None
        for ts, value in lows[lows.index >= year.index[0]].items():
            prior = lows[(lows.index < ts) & (lows.index >= ts - YEAR)]
            if not len(prior) or value <= float(prior.min()):
                last_new_low = ts
        if last_new_low is not None:
            days_since = int((completed.index > last_new_low).sum())

    parts = []
    if nepal_price is not None and low is not None and high is not None:
        since = window[0][0]
        above, below = nepal_price - low[1], high[1] - nepal_price
        if above <= 0:
            parts.append(f"{label} in Nepal is at its lowest price since {_short(since)}.")
        elif below <= 0:
            parts.append(f"{label} in Nepal is at its highest price since {_short(since)}.")
        else:
            parts.append(
                f"{label} in Nepal is {_rupees(above)} above its lowest price since {_short(since)} "
                f"and {_rupees(below)} below its highest."
            )
    world = world_now if world_now is not None else (float(completed["close"].iloc[-1]) if len(completed) else None)
    if world is not None and w_low:
        if days_since is not None and days_since <= RECENT_LOW_DAYS:
            when = "in the last completed day" if days_since == 0 else f"{days_since} day{'s' if days_since != 1 else ''} ago"
            parts.append(f"World {label.lower()} made its lowest price of the past year {when}.")
        else:
            parts.append(f"World {label.lower()} is {(world / w_low - 1) * 100:.0f}% above its lowest price of the past year.")

    return Position(
        nepal_price=nepal_price,
        nepal_low=low[1] if low else None,
        nepal_low_date=low[0] if low else None,
        nepal_high=high[1] if high else None,
        nepal_high_date=high[0] if high else None,
        nepal_window_start=window[0][0] if window else None,
        nepal_publications=len(window),
        above_low_npr=(nepal_price - low[1]) if low else None,
        below_high_npr=(high[1] - nepal_price) if high else None,
        world_price=world,
        world_52w_low=w_low,
        world_52w_high=w_high,
        days_since_52w_low=days_since,
        plain=" ".join(parts) or None,
    )


def round_rupees(value: float, step: float) -> float:
    return round(value / step) * step


def key_levels(
    levels_by_tf: dict[str, list[dict]],
    states_by_tf: dict[str, list[dict]],
    world_now: float | None,
    rupees_per_usd_oz: float | None,
    step: float,
) -> list[KeyLevel]:
    """Floors nearest first, then ceilings nearest first. Level dicts as in ``levels.as_dicts``."""
    if world_now is None:
        return []
    state_of = {s["level_id"]: s["state"] for states in states_by_tf.values() for s in states}
    chosen: dict[str, list[KeyLevel]] = {"floor": [], "ceiling": []}
    taken: list[float] = []
    for kind in ("floor", "ceiling"):
        for tf in LEVEL_TIMEFRAMES:
            candidates = [
                lv for lv in levels_by_tf.get(tf, [])
                if (lv["price"] < world_now if kind == "floor" else lv["price"] > world_now)
            ]
            for lv in sorted(candidates, key=lambda lv: abs(lv["price"] - world_now)):
                if len(chosen[kind]) >= LEVELS_PER_SIDE:
                    break
                if any(abs(lv["price"] / t - 1) < LEVEL_MIN_GAP for t in taken):
                    continue
                taken.append(lv["price"])
                chosen[kind].append(
                    KeyLevel(
                        kind=kind,
                        timeframe=tf,
                        world_price=lv["price"],
                        rupees=round_rupees(lv["price"] * rupees_per_usd_oz, step) if rupees_per_usd_oz else None,
                        touches=int(lv.get("touches") or 0),
                        manual=bool(lv.get("manual")),
                        state=state_of.get(lv["id"], "none"),
                    )
                )
    floors = sorted(chosen["floor"], key=lambda k: world_now - k.world_price)
    ceilings = sorted(chosen["ceiling"], key=lambda k: k.world_price - world_now)
    return floors + ceilings
