"""Confirmed pivots, support/resistance levels, swing structure, and level states.

A pivot at bar i needs two lower highs (or higher lows) on each side, so it only becomes
known when bar i+2 closes. ``available_at`` records that moment to prevent look-ahead.

Level states, always named with their timeframe:
- touch: the latest completed bar entered the level's tolerance zone (±0.25 ATR).
- intrabar_breach: the live price is beyond the level, but no bar has closed beyond it.
- confirmed_break: a completed bar closed at least 0.25 ATR beyond the level.
- retest: after a confirmed break, a later bar touched the level and closed on the broken side.
- reclaim: after a confirmed break, a later bar closed back on the original side.
"""

from dataclasses import asdict, dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from gold_advisor.domain import Timeframe

VERSION = "levels-1"
PIVOT_SIDE_BARS = 2
CLUSTER_ATR = 0.25
BREAK_ATR = 0.25
TOUCH_ATR = 0.25
LOOKBACK_BARS = 300
EVENT_LOOKBACK_BARS = 12
MAX_LEVELS_PER_SIDE = 4


@dataclass(frozen=True)
class Pivot:
    kind: str  # "high" | "low"
    at: datetime
    available_at: datetime
    price: float


@dataclass(frozen=True)
class Level:
    id: str
    timeframe: str
    price: float
    kind: str  # "support" | "resistance"
    touches: int
    last_pivot_at: datetime | None
    manual: bool = False


@dataclass(frozen=True)
class LevelState:
    level_id: str
    timeframe: str
    price: float
    kind: str
    state: str  # none | touch | intrabar_breach | confirmed_break | retest | reclaim
    direction: str | None  # "down" through support, "up" through resistance
    since: datetime | None


def find_pivots(bars: pd.DataFrame, timeframe: Timeframe) -> list[Pivot]:
    h, l = bars["high"].to_numpy(float), bars["low"].to_numpy(float)
    idx = bars.index
    k = PIVOT_SIDE_BARS
    pivots: list[Pivot] = []
    for i in range(k, len(bars) - k):
        confirm = idx[i + k] + timeframe.duration
        if h[i] > h[i - k : i].max() and h[i] > h[i + 1 : i + k + 1].max():
            pivots.append(Pivot("high", idx[i], confirm, float(h[i])))
        if l[i] < l[i - k : i].min() and l[i] < l[i + 1 : i + k + 1].min():
            pivots.append(Pivot("low", idx[i], confirm, float(l[i])))
    return pivots


def cluster_levels(pivots: list[Pivot], atr: float, close: float, timeframe: Timeframe) -> list[Level]:
    if not pivots or not atr or np.isnan(atr):
        return []
    ordered = sorted(pivots, key=lambda p: p.price)
    clusters: list[list[Pivot]] = [[ordered[0]]]
    for p in ordered[1:]:
        if p.price - clusters[-1][-1].price <= CLUSTER_ATR * atr:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    levels = []
    for group in clusters:
        price = float(np.mean([p.price for p in group]))
        kind = "support" if price < close else "resistance"
        levels.append(
            Level(
                id=f"{timeframe.value}-{round(price)}",
                timeframe=timeframe.value,
                price=round(price, 2),
                kind=kind,
                touches=len(group),
                last_pivot_at=max(p.at for p in group),
            )
        )
    supports = sorted((x for x in levels if x.kind == "support"), key=lambda x: close - x.price)
    resistances = sorted((x for x in levels if x.kind == "resistance"), key=lambda x: x.price - close)
    return supports[:MAX_LEVELS_PER_SIDE] + resistances[:MAX_LEVELS_PER_SIDE]


def manual_level(price: float, close: float, timeframe: Timeframe) -> Level:
    return Level(
        id=f"watch-{round(price)}",
        timeframe=timeframe.value,
        price=price,
        kind="support" if price < close else "resistance",
        touches=0,
        last_pivot_at=None,
        manual=True,
    )


def swing_structure(pivots: list[Pivot], now: datetime) -> int:
    """+1 higher highs and higher lows, -1 lower highs and lower lows, 0 otherwise."""
    known = [p for p in pivots if p.available_at <= now]
    highs = [p.price for p in known if p.kind == "high"][-2:]
    lows = [p.price for p in known if p.kind == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return 0
    if highs[1] > highs[0] and lows[1] > lows[0]:
        return 1
    if highs[1] < highs[0] and lows[1] < lows[0]:
        return -1
    return 0


def level_state(level: Level, ind: pd.DataFrame, live_price: float | None) -> LevelState:
    """Classify the most recent interaction of completed bars (and the live price) with a level."""
    recent = ind.tail(EVENT_LOOKBACK_BARS + 1)
    atr = recent["atr_14"].iloc[-1] if not recent.empty else np.nan
    base = LevelState(level.id, level.timeframe, level.price, level.kind, "none", None, None)
    if recent.empty or np.isnan(atr):
        return base
    closes, highs, lows = recent["close"].to_numpy(float), recent["high"].to_numpy(float), recent["low"].to_numpy(float)
    times = recent.index
    # Judge the break direction from where price started the window, so a support that
    # broke recently (and now sits above price) is still reported as a broken support.
    was_support = closes[0] > level.price
    sign = -1 if was_support else 1  # direction a break moves price
    kind = "support" if was_support else "resistance"
    level = Level(level.id, level.timeframe, level.price, kind, level.touches, level.last_pivot_at, level.manual)
    beyond = lambda x: sign * (x - level.price) >= BREAK_ATR * atr  # noqa: E731
    original_side = lambda x: sign * (x - level.price) < 0  # noqa: E731

    break_i = None
    for i in range(1, len(closes)):
        if beyond(closes[i]) and not beyond(closes[i - 1]):
            break_i = i
    direction = "down" if sign < 0 else "up"
    if break_i is not None:
        for j in range(break_i + 1, len(closes)):
            if original_side(closes[j]):
                return LevelState(level.id, level.timeframe, level.price, level.kind, "reclaim", direction, times[j])
        last = len(closes) - 1
        if last > break_i and lows[last] - TOUCH_ATR * atr <= level.price <= highs[last] + TOUCH_ATR * atr:
            return LevelState(level.id, level.timeframe, level.price, level.kind, "retest", direction, times[last])
        return LevelState(level.id, level.timeframe, level.price, level.kind, "confirmed_break", direction, times[break_i])
    if live_price is not None and sign * (live_price - level.price) > 0:
        return LevelState(level.id, level.timeframe, level.price, level.kind, "intrabar_breach", direction, None)
    if lows[-1] - TOUCH_ATR * atr <= level.price <= highs[-1] + TOUCH_ATR * atr:
        return LevelState(level.id, level.timeframe, level.price, level.kind, "touch", None, times[-1])
    return base


def as_dicts(items) -> list[dict]:
    return [{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in asdict(x).items()} for x in items]
