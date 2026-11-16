"""Silver trading plan (the Trade screen) and its profit and loss. Pure functions.

The app never places orders. It shows a plan and values what the owner says they did.

Starting rule (2026-11-16), to be tested before it is shown as advice (``backtest.trade_replay``):
- buy the first half when three completed daily bars make no new low and a daily close is back above
  the nearest broken floor (a 1D support in the "reclaim" state);
- buy the second half on a daily close above the next ceiling (the nearest 1D resistance above the
  first buy);
- take profit at the ceiling after that;
- cut the loss on a daily close below the low made before the first buy.

Levels are world prices (US$/oz); the screen shows them in rupees per tola through the snapshot's
``rupees_per_usd_oz``. Selling back to a shop loses the buy-back gap, which the owner enters; until
then no profit figures are shown.
"""

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

VERSION = "trade-1"
# Off until the owner approves the replay numbers: the plan is labelled as a trial, not advice.
APPROVED = False
DEFAULT_BUDGET = 100_000
NO_NEW_LOW_BARS = 3
SELLOFF_LOOKBACK_BARS = 20

STAY_OUT, BUY_FIRST, BUY_SECOND, HOLD, TAKE_PROFIT, CUT_LOSS = (
    "stay_out", "buy_first_half", "buy_second_half", "hold", "take_profit", "cut_loss",
)
PLAIN = {
    STAY_OUT: "Stay out for now.",
    BUY_FIRST: "Buy the first half.",
    BUY_SECOND: "Buy the second half.",
    HOLD: "Hold what you have.",
    TAKE_PROFIT: "Take profit: sell.",
    CUT_LOSS: "Cut the loss: sell.",
}


@dataclass(frozen=True)
class MarketFacts:
    """What the rule reads from completed daily bars at one moment, in world US$/oz."""

    close: float  # last completed daily close
    no_new_low: bool  # the last 3 completed bars stayed above the low before them
    selloff_low: float | None  # lowest low of the 20 bars before the last 3: the cut-loss level for a new buy
    reclaimed_floor: float | None  # nearest broken-then-reclaimed 1D support below the close
    levels: tuple[float, ...]  # every 1D level price (not the owner's watch levels), low to high


@dataclass(frozen=True)
class Holding:
    parts: int  # 1 or 2 halves bought since the position was last flat
    quantity_tola: float
    cost_npr: float  # total rupees paid for the open quantity
    entry_world: float  # world price at the first buy
    cut_world: float | None  # the low made before the first buy


@dataclass(frozen=True)
class Plan:
    state: str
    plain: str
    second_world: float | None  # daily close above this buys the second half
    target_world: float | None  # take profit here
    cut_world: float | None  # a daily close below this cuts the loss


@dataclass
class Trade:
    side: str  # "buy" | "sell"
    quantity_tola: float
    price_npr: float
    traded_at: datetime


@dataclass(frozen=True)
class Book:
    """The owner's recorded trades, averaged: open position and realised result (after the gap)."""

    quantity_tola: float
    cost_npr: float  # of the open quantity, at average cost
    parts: int  # buys since the position was last flat
    first_buy_at: datetime | None
    realised_npr: float  # sales minus the average cost of what was sold; sale prices as entered
    trades: int


def market_facts(d1: pd.DataFrame, level_states: list[dict], levels: list[dict]) -> MarketFacts | None:
    """``d1``: completed daily bars (high/low/close) oldest first. Level dicts as in the snapshot."""
    if len(d1) < NO_NEW_LOW_BARS + 2:
        return None
    close = float(d1["close"].iloc[-1])
    recent = d1["low"].iloc[-NO_NEW_LOW_BARS:]
    before = d1["low"].iloc[-NO_NEW_LOW_BARS - SELLOFF_LOOKBACK_BARS : -NO_NEW_LOW_BARS]
    selloff = float(before.min()) if len(before) else None
    reclaimed = [
        s["price"] for s in level_states
        if s.get("state") == "reclaim" and s.get("direction") == "down" and s["price"] < close
    ]
    prices = sorted({float(lv["price"]) for lv in levels if not lv.get("manual")})
    return MarketFacts(
        close=close,
        no_new_low=selloff is not None and float(recent.min()) > selloff,
        selloff_low=selloff,
        reclaimed_floor=max(reclaimed) if reclaimed else None,
        levels=tuple(prices),
    )


def plan(facts: MarketFacts | None, holding: Holding | None) -> Plan:
    if facts is None:
        return Plan(STAY_OUT, "Not enough daily price history for a plan.", None, None, None)
    if holding is None or holding.quantity_tola <= 0:
        ceilings = [lv for lv in facts.levels if lv > facts.close]
        second, target = (ceilings[0] if ceilings else None), (ceilings[1] if len(ceilings) > 1 else None)
        if facts.no_new_low and facts.reclaimed_floor is not None:
            return Plan(BUY_FIRST, PLAIN[BUY_FIRST], second, target, facts.selloff_low)
        return Plan(STAY_OUT, PLAIN[STAY_OUT], second, target, facts.selloff_low)
    above_entry = [lv for lv in facts.levels if lv > holding.entry_world]
    second = above_entry[0] if above_entry else None
    target = above_entry[1] if len(above_entry) > 1 else None
    if holding.cut_world is not None and facts.close < holding.cut_world:
        return Plan(CUT_LOSS, PLAIN[CUT_LOSS], second, target, holding.cut_world)
    if holding.parts >= 2:
        if target is not None and facts.close >= target:
            return Plan(TAKE_PROFIT, PLAIN[TAKE_PROFIT], second, target, holding.cut_world)
        # After the second half, the next ceiling above the close is the target.
        target = next((lv for lv in facts.levels if lv > facts.close), target)
        return Plan(HOLD, PLAIN[HOLD], None, target, holding.cut_world)
    if second is not None and facts.close > second:
        return Plan(BUY_SECOND, PLAIN[BUY_SECOND], second, target, holding.cut_world)
    return Plan(HOLD, PLAIN[HOLD], second, target, holding.cut_world)


def book(trades: list[Trade]) -> Book:
    """Average-cost book over the recorded trades, oldest first."""
    qty = cost = realised = 0.0
    parts, first_at = 0, None
    for t in sorted(trades, key=lambda t: t.traded_at):
        if t.side == "buy":
            if qty <= 1e-9:
                parts, first_at = 0, t.traded_at
            qty += t.quantity_tola
            cost += t.quantity_tola * t.price_npr
            parts += 1
        else:
            sold = min(t.quantity_tola, qty)
            avg = cost / qty if qty else 0.0
            realised += sold * (t.price_npr - avg)
            qty -= sold
            cost -= sold * avg
            if qty <= 1e-9:
                qty, cost, parts, first_at = 0.0, 0.0, 0, None
    return Book(round(qty, 4), round(cost, 2), parts, first_at, round(realised, 2), len(trades))


@dataclass
class ReplayTrade:
    bought: list[tuple[str, float, float]] = field(default_factory=list)  # (day, tola, price)
    sold_on: str | None = None
    sold_price: float | None = None
    result_npr: float | None = None
    exit: str | None = None


def replay(days: list[tuple[str, float, MarketFacts | None]], gap: float, budget: float = DEFAULT_BUDGET) -> dict:
    """``days``: (day, Nepal price per tola, facts) oldest first. Buys at the Nepal price, sells at the
    Nepal price less ``gap``. Each half is half the budget."""
    holding: Holding | None = None
    done: list[ReplayTrade] = []
    current: ReplayTrade | None = None
    for day, price, facts in days:
        if facts is None:
            continue
        p = plan(facts, holding)
        if p.state == BUY_FIRST and holding is None:
            qty = budget / 2 / price
            holding = Holding(1, qty, qty * price, facts.close, facts.selloff_low)
            current = ReplayTrade(bought=[(day, qty, price)])
        elif p.state == BUY_SECOND and holding is not None and holding.parts == 1:
            qty = budget / 2 / price
            holding = Holding(2, holding.quantity_tola + qty, holding.cost_npr + qty * price, holding.entry_world, holding.cut_world)
            current.bought.append((day, qty, price))
        elif p.state in (TAKE_PROFIT, CUT_LOSS) and holding is not None:
            proceeds = holding.quantity_tola * price * (1 - gap)
            current.sold_on, current.sold_price = day, price
            current.result_npr, current.exit = proceeds - holding.cost_npr, p.state
            done.append(current)
            holding, current = None, None
    wins = sum(1 for t in done if t.result_npr > 0)
    return {
        "gap_pct": gap * 100,
        "trades": len(done),
        "winning": wins,
        "share_winning": wins / len(done) if done else None,
        "total_npr": round(sum(t.result_npr for t in done), 2),
        "open_at_end": current is not None,
        "first_day": days[0][0] if days else None,
        "last_day": days[-1][0] if days else None,
    }


def money(plan_: Plan, nepal_price: float | None, factor: float | None, step: float, budget: float,
          gap: float | None, held: Book | None) -> dict:
    """Rupee levels, quantities and (only once the gap is known) profit at the target and loss at
    the cut-loss level for the position held, or for a first half bought now when flat."""
    to_npr = lambda w: round(w * factor / step) * step if (w is not None and factor) else None  # noqa: E731
    half_qty = round(budget / 2 / nepal_price, 2) if nepal_price else None
    out = {
        "second_npr": to_npr(plan_.second_world),
        "target_npr": to_npr(plan_.target_world),
        "cut_npr": to_npr(plan_.cut_world),
        "half_quantity_tola": half_qty,
        "profit_at_target_npr": None,
        "loss_at_cut_npr": None,
    }
    if gap is None:
        return out
    if held is not None and held.quantity_tola > 0:
        qty, cost = held.quantity_tola, held.cost_npr
    elif half_qty and nepal_price:
        qty, cost = half_qty, half_qty * nepal_price
    else:
        return out
    if out["target_npr"] is not None:
        out["profit_at_target_npr"] = round(qty * out["target_npr"] * (1 - gap) - cost, 2)
    if out["cut_npr"] is not None:
        out["loss_at_cut_npr"] = round(qty * out["cut_npr"] * (1 - gap) - cost, 2)
    return out
