from datetime import datetime, timedelta

import pandas as pd

from gold_advisor import trading as t
from gold_advisor.domain import UTC

T0 = datetime(2026, 11, 1, 6, tzinfo=UTC)


def test_buy_and_sell_give_the_right_position_and_realised_result():
    trades = [
        t.Trade("buy", 10, 3600, T0),
        t.Trade("buy", 10, 3500, T0 + timedelta(days=2)),
        t.Trade("sell", 5, 3800, T0 + timedelta(days=5)),
    ]
    b = t.book(trades)
    assert (b.quantity_tola, b.cost_npr, b.parts) == (15, 15 * 3550, 2)
    assert b.realised_npr == 5 * (3800 - 3550)
    flat = t.book(trades + [t.Trade("sell", 15, 3400, T0 + timedelta(days=6))])
    assert flat.quantity_tola == 0 and flat.first_buy_at is None and flat.realised_npr == 1250 - 15 * 150


def facts(close, no_new_low=True, reclaimed=True, res=(50.0, 52.0)):
    return t.MarketFacts(close, no_new_low, 44.0, 45.0 if reclaimed else None, (45.0, *res))


def test_plan_moves_through_its_states():
    assert t.plan(facts(46.0, no_new_low=False), None).state == t.STAY_OUT
    first = t.plan(facts(46.0), None)
    assert first.state == t.BUY_FIRST and (first.second_world, first.target_world, first.cut_world) == (50.0, 52.0, 44.0)
    half = t.Holding(1, 10, 36000, 46.0, 44.0)
    assert t.plan(facts(48.0), half).state == t.HOLD
    assert t.plan(facts(50.5), half).state == t.BUY_SECOND
    assert t.plan(facts(43.5), half).state == t.CUT_LOSS
    full = t.Holding(2, 20, 72000, 46.0, 44.0)
    assert t.plan(facts(52.0, res=(50.0, 52.0, 55.0)), full).state == t.TAKE_PROFIT


def test_profit_figures_wait_for_the_buy_back_gap():
    p = t.plan(facts(46.0), None)
    without = t.money(p, 3600, 78.0, 5, 100_000, None, None)
    assert without["profit_at_target_npr"] is None and without["target_npr"] == round(52 * 78 / 5) * 5
    with_gap = t.money(p, 3600, 78.0, 5, 100_000, 0.02, None)
    qty = round(50_000 / 3600, 2)
    assert with_gap["profit_at_target_npr"] == round(qty * with_gap["target_npr"] * 0.98 - qty * 3600, 2)


def test_market_facts_read_completed_daily_bars():
    idx = pd.date_range("2026-10-01", periods=30, freq="1D", tz=UTC)
    low = [50 - i * 0.3 for i in range(27)] + [42.5, 42.6, 42.7]  # lows stop falling for the last 3 bars
    d1 = pd.DataFrame({"high": [x + 1 for x in low], "low": low, "close": [x + 0.5 for x in low]}, index=idx)
    f = t.market_facts(d1, [{"price": 42.8, "state": "reclaim", "direction": "down"}], [{"price": 45.0}, {"price": 47.0, "manual": True}])
    assert f.no_new_low and f.reclaimed_floor == 42.8 and f.levels == (45.0,)
