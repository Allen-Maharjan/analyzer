from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from gold_advisor import backtest
from gold_advisor.assets import GOLD
from gold_advisor.decision import nepal
from gold_advisor.domain import UTC, Timeframe


def _history(days: int = 160) -> backtest.History:
    rng = np.random.default_rng(7)
    idx = pd.date_range(datetime(2025, 1, 1, tzinfo=UTC), periods=days * 24, freq="1h")
    close = 2600 * np.exp(np.cumsum(rng.normal(0, 0.003, len(idx))))
    h1 = pd.DataFrame({"open": np.r_[close[0], close[:-1]], "close": close}, index=idx)
    h1["high"] = h1[["open", "close"]].max(axis=1) * 1.001
    h1["low"] = h1[["open", "close"]].min(axis=1) * 0.999
    agg = {"open": "first", "high": "max", "low": "min", "close": "last"}
    bars = {Timeframe.H1: h1, Timeframe.H4: h1.resample("4h").agg(agg), Timeframe.D1: h1.resample("1D").agg(agg)}
    by_end = pd.Series(close, index=idx + timedelta(hours=1))
    pubs = []
    for d in pd.date_range(date(2025, 1, 2), periods=days - 2, freq="1D").date:
        if d.weekday() == 5:
            continue
        at = nepal.publication_instant(nepal.Publication(d, None, 0))[0]
        pubs.append(nepal.Publication(d, None, round(float(by_end[by_end.index <= at].iloc[-1]) * 133 * 0.375 * 1.1, -2)))
    fx = pd.Series(133.0, index=pd.date_range("2024-12-01", periods=days + 40, freq="1D"))
    return backtest.History(bars, pubs, fx, [(datetime(2025, 3, 19, 18, tzinfo=UTC), "FOMC statement")])


def test_replay_never_sees_the_future():
    history = _history()
    days = backtest.run(history, GOLD, date.min, date.max)
    assert len(days) > 60 and {d.decision for d in days}
    assert backtest.lookahead_check(history, GOLD, days, sample=len(days)) == []


def test_summary_compares_advice_with_buying_on_day_one():
    report = backtest.summarise(backtest.run(_history(), GOLD, date.min, date.max))
    assert report["overall"]["windows"] >= 15
    assert sum(report["decisions"].values()) == report["days"]
    assert report["plain"]
