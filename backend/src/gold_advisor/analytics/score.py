"""Auditable forecast score. Every component is −100…+100 and keeps its inputs.

Weights are fixed. A missing component contributes zero and the remaining weights are
NOT scaled up; ``coverage`` reports how much of the total weight had data.
"""

import math
from dataclasses import dataclass, field

import pandas as pd

from gold_advisor.domain import Outlook, Timeframe

VERSION = "score-1"
COMPONENT_WEIGHTS = {"trend": 0.25, "momentum": 0.20, "structure": 0.20, "macro": 0.20, "event_risk": 0.10}
AI_MAX_ADJUSTMENT = 5.0
TIMEFRAME_WEIGHTS = {Timeframe.M15: 0.05, Timeframe.H1: 0.15, Timeframe.H4: 0.30, Timeframe.D1: 0.40, Timeframe.W1: 0.10}
BULLISH_ABOVE, BEARISH_BELOW = 20.0, -20.0
EMA_FAST, EMA_SLOW, SLOPE_BARS = "ema_21", "ema_50", 5
STRUCTURE_SWING_POINTS, STRUCTURE_BREAK_POINTS, STRUCTURE_RECLAIM_POINTS = 50.0, 40.0, 25.0
MACRO_LOOKBACK_DAYS, MACRO_CHANGE_DAYS = 252, 5
EVENT_BLOCK_HOURS, EVENT_HALF_HOURS = 24, 48


def _clip(x: float) -> float:
    return max(-100.0, min(100.0, x))


@dataclass
class Component:
    name: str
    value: float | None
    inputs: dict = field(default_factory=dict)
    note: str | None = None


def trend(ind: pd.DataFrame) -> Component:
    if len(ind) <= SLOPE_BARS:
        return Component("trend", None, note="not enough bars")
    last, prev = ind.iloc[-1], ind.iloc[-1 - SLOPE_BARS]
    atr, fast, slow, fast_prev = last["atr_14"], last[EMA_FAST], last[EMA_SLOW], prev[EMA_FAST]
    if any(pd.isna(v) or v == 0 for v in (atr,)) or any(pd.isna(v) for v in (fast, slow, fast_prev)):
        return Component("trend", None, note="indicator warm-up")
    separation = (fast - slow) / atr
    slope = (fast - fast_prev) / atr
    value = _clip(60 * math.tanh(separation / 2) + 40 * math.tanh(slope / 1.5))
    return Component("trend", round(value, 2), {"ema_separation_atr": round(separation, 3), "ema21_slope_atr": round(slope, 3)})


def momentum(ind: pd.DataFrame) -> Component:
    last = ind.iloc[-1] if len(ind) else None
    if last is None or any(pd.isna(last[k]) for k in ("rsi_14", "macd_hist", "atr_14")) or last["atr_14"] == 0:
        return Component("momentum", None, note="indicator warm-up")
    rsi_part = max(-1.0, min(1.0, (last["rsi_14"] - 50) / 25))
    macd_part = math.tanh(last["macd_hist"] / (0.25 * last["atr_14"]))
    value = _clip(100 * (0.5 * rsi_part + 0.5 * macd_part))
    return Component(
        "momentum",
        round(value, 2),
        {"rsi_14": round(float(last["rsi_14"]), 2), "macd_hist_atr": round(float(last["macd_hist"] / last["atr_14"]), 3)},
    )


def structure(swing: int, states: list[dict]) -> Component:
    points = STRUCTURE_SWING_POINTS * swing
    events = []
    for s in states:
        if s["state"] in ("confirmed_break", "retest"):
            points += STRUCTURE_BREAK_POINTS * (-1 if s["direction"] == "down" else 1)
            events.append(f"{s['state']} {s['direction']} {s['level_id']}")
        elif s["state"] == "reclaim":
            points += STRUCTURE_RECLAIM_POINTS * (1 if s["direction"] == "down" else -1)
            events.append(f"reclaim {s['level_id']}")
    return Component("structure", round(_clip(points), 2), {"swing": swing, "events": events})


def aggregate_technical(per_tf: dict[Timeframe, dict[str, Component]]) -> dict[str, Component]:
    out = {}
    for name in ("trend", "momentum", "structure"):
        total, covered, parts = 0.0, 0.0, {}
        for tf, weight in TIMEFRAME_WEIGHTS.items():
            comp = per_tf.get(tf, {}).get(name)
            if comp is not None and comp.value is not None:
                total += weight * comp.value
                covered += weight
                parts[tf.value] = comp.value
        value = round(total, 2) if covered else None
        out[name] = Component(name, value, {"by_timeframe": parts, "timeframe_coverage": round(covered, 2)})
    return out


def _zscore_change(series: pd.Series) -> float | None:
    s = series.dropna()
    if len(s) < MACRO_LOOKBACK_DAYS // 2:
        return None
    changes = s.diff(MACRO_CHANGE_DAYS).dropna().tail(MACRO_LOOKBACK_DAYS)
    std = changes.std()
    if not std or pd.isna(std):
        return None
    return float(changes.iloc[-1] / std)


def macro(real_10y: pd.Series | None, nominal_2y: pd.Series | None, dollar: pd.Series | None) -> Component:
    """Rising real yields, short yields, or the dollar are treated as headwinds for gold."""
    parts = {
        "real_10y": (_zscore_change(real_10y) if real_10y is not None else None, 0.4),
        "nominal_2y": (_zscore_change(nominal_2y) if nominal_2y is not None else None, 0.3),
        "dollar": (_zscore_change(dollar) if dollar is not None else None, 0.3),
    }
    total, covered = 0.0, 0.0
    for z, w in parts.values():
        if z is not None:
            total += -w * z
            covered += w
    inputs = {k: (round(z, 3) if z is not None else None) for k, (z, _) in parts.items()}
    inputs["coverage"] = round(covered, 2)
    if not covered:
        return Component("macro", None, inputs, "no macro series available")
    return Component("macro", round(_clip(100 * math.tanh(total / 2)), 2), inputs,
                     None if covered == 1 else "dollar index not collected yet")


def event_safety_factor(hours_to_next_major: float | None) -> float | None:
    if hours_to_next_major is None:
        return None
    if hours_to_next_major <= EVENT_BLOCK_HOURS:
        return 0.0
    if hours_to_next_major <= EVENT_HALF_HOURS:
        return 0.5
    return 1.0


def event_risk(direction: float | None, hours_to_next_major: float | None) -> Component:
    factor = event_safety_factor(hours_to_next_major)
    if factor is None or direction is None:
        return Component("event_risk", None, {"hours_to_next_major_event": hours_to_next_major}, "event calendar unavailable")
    return Component(
        "event_risk",
        round(direction * factor, 2),
        {"base_direction": round(direction, 2), "safety_factor": factor, "hours_to_next_major_event": hours_to_next_major},
    )


def combine(components: dict[str, Component]) -> tuple[float | None, float]:
    total, covered = 0.0, 0.0
    for name, weight in COMPONENT_WEIGHTS.items():
        comp = components.get(name)
        if comp is not None and comp.value is not None:
            total += weight * comp.value
            covered += weight
    return (round(total, 2) if covered else None), round(covered / sum(COMPONENT_WEIGHTS.values()), 2)


def base_direction(components: dict[str, Component]) -> float | None:
    """Weighted mean of the non-event components; the event factor scales this."""
    total, weights = 0.0, 0.0
    for name in ("trend", "momentum", "structure", "macro"):
        comp = components.get(name)
        if comp is not None and comp.value is not None:
            total += COMPONENT_WEIGHTS[name] * comp.value
            weights += COMPONENT_WEIGHTS[name]
    return total / weights if weights else None


def outlook(score: float | None) -> Outlook | None:
    if score is None:
        return None
    if score > BULLISH_ABOVE:
        return Outlook.BULLISH
    if score < BEARISH_BELOW:
        return Outlook.BEARISH
    return Outlook.NEUTRAL
