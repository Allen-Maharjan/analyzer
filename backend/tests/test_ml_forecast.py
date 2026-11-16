import numpy as np
import pandas as pd
import pytest

from gold_advisor.analytics import ml_forecast as ml


def _bars(n: int, seed: int = 0, start: str = "2015-01-01") -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.005, n)) * close
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + spread,
                         "low": np.minimum(open_, close) - spread, "close": close}, index=idx)


def _macro(index: pd.DatetimeIndex) -> dict[str, pd.Series]:
    rng = np.random.default_rng(9)
    return {sid: pd.Series(4 + np.cumsum(rng.normal(0, 0.02, len(index))), index=index) for sid in ml.MACRO_SERIES}


def test_features_never_use_the_future():
    bars, other = _bars(400), _bars(400, seed=1)
    macro = _macro(bars.index)
    full = ml.build_features(bars, other, macro)
    for cut in (250, 320, 399):
        day = bars.index[cut]
        part = ml.build_features(bars.loc[:day], other.loc[:day], {k: v.loc[:day] for k, v in macro.items()})
        pd.testing.assert_series_equal(full.loc[day], part.loc[day], check_names=False)


def test_macro_is_lagged_one_business_day():
    bars = _bars(30)
    macro = {"DGS10": pd.Series(np.arange(30, dtype=float), index=bars.index)}
    feats = ml.build_features(bars, None, macro)
    # On day i the model may only know the value dated day i-1.
    assert feats["DGS10_level"].iloc[10] == 9.0


def test_labels_compare_with_the_close_horizon_days_later():
    close = pd.Series([1.0, 2.0, 1.5, 1.5, 3.0])
    assert ml.labels(close, 1).tolist()[:4] == [1.0, 0.0, 0.0, 1.0]
    assert np.isnan(ml.labels(close, 1).iloc[-1])
    assert ml.labels(close, 3).tolist()[:2] == [1.0, 1.0]
    assert ml.labels(close, 3).iloc[2:].isna().all()


def test_daily_bars_drop_weekend_stubs():
    idx = pd.to_datetime(["2026-11-13", "2026-11-15", "2026-11-16"], utc=True)
    df = pd.DataFrame({"open": [1, 2, 3], "high": [1, 2, 3], "low": [1, 2, 3], "close": [1, 2, 3]}, index=idx)
    assert [d.day for d in ml.daily_bars(df).index] == [13, 16]


def test_walk_forward_purges_and_finds_no_edge_in_a_random_walk():
    pytest.importorskip("lightgbm")
    bars = _bars(900, seed=3)
    feats = ml.build_features(bars, _bars(900, seed=4), _macro(bars.index))
    wf = ml.walk_forward(feats, bars["close"], 3, min_train=400, step=63, params={"n_estimators": 40})
    days = list(feats.index)
    for fold in wf.folds:
        # At least ``horizon`` trading days between the last training day and the first test day.
        assert days.index(fold.test_start) - days.index(fold.train_end) > 3
    ev = ml.evaluate(wf)
    assert ev["status"] == "ok" and ev["tested_days"] > 300
    assert ml.verdict(ev) != "useful edge"
    assert abs(ev["hit_rate"] - 0.5) < 0.1


def test_walk_forward_finds_a_planted_signal():
    pytest.importorskip("lightgbm")
    bars = _bars(900, seed=5)
    feats = ml.build_features(bars, None, None)
    # Next day's move follows the sign of today's candle body: a real, learnable pattern.
    close = bars["close"].copy()
    body = np.sign(feats["body"].fillna(0).to_numpy())
    for i in range(1, len(close)):
        close.iloc[i] = close.iloc[i - 1] * (1 + 0.004 * body[i - 1] + 0.001 * np.sign(np.sin(i)))
    ev = ml.evaluate(ml.walk_forward(feats, close, 1, min_train=400, step=63, params={"n_estimators": 60}))
    assert ev["hit_rate"] > 0.8 and ml.verdict(ev) == "useful edge"
