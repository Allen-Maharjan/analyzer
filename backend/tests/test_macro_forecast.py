import numpy as np
import pandas as pd

from gold_advisor.analytics import macro_forecast as mf


def _series(n: int, seed: int = 0, start: str = "2000-01-03") -> tuple[pd.Series, dict[str, pd.Series]]:
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=n)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, n))), index=idx)
    real = pd.Series(1 + np.cumsum(rng.normal(0, 0.03, n)), index=idx)
    dollar = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.003, n))), index=idx)
    return close, {"DFII10": real, "DTWEXBGS": dollar}


def test_forecast_made_on_a_day_ignores_everything_after_it():
    close, macro = _series(2400)
    h = 63
    full = mf.walk_forward(close, macro, h, min_train_years=3).windows
    day = full.index[len(full) // 2]
    cut = close.index.get_loc(day) + h  # keep exactly what is needed to know that window's answer
    part = mf.walk_forward(close.iloc[: cut + 1], {k: v.iloc[: cut + 1] for k, v in macro.items()}, h,
                           min_train_years=3).windows
    pd.testing.assert_series_equal(full.loc[day], part.loc[day], check_names=False)


def test_test_windows_do_not_overlap():
    close, macro = _series(2400, seed=1)
    w = mf.walk_forward(close, macro, 63, min_train_years=3).windows
    gaps = np.diff([close.index.get_loc(d) for d in w.index])
    assert (gaps >= 63).all()


def test_random_walk_is_not_called_useful():
    close, macro = _series(5000, seed=2)
    ev = mf.evaluate(mf.walk_forward(close, macro, 63, min_train_years=4))
    assert ev["models"]["macro"]["verdict"] != "useful"
    assert ev["models"]["trend"]["verdict"] != "useful"


def test_a_real_rate_signal_is_found():
    rng = np.random.default_rng(3)
    n, h = 5000, 63
    idx = pd.bdate_range("2000-01-03", periods=n)
    real = pd.Series(1 + np.cumsum(rng.normal(0, 0.03, n)), index=idx)
    # Price drifts down while real rates are high (known in advance): a learnable relationship.
    step = -0.002 * (real - real.mean()).to_numpy() + rng.normal(0, 0.003, n)
    close = pd.Series(100 * np.exp(np.cumsum(np.r_[0, step[:-1]])), index=idx)
    macro = {"DFII10": real.shift(-1).ffill(), "DTWEXBGS": pd.Series(100.0, index=idx)}
    ev = mf.evaluate(mf.walk_forward(close, macro, h, min_train_years=4))
    assert ev["models"]["macro"]["verdict"] == "useful"


def test_dollar_join_rescales_the_older_index():
    idx = pd.bdate_range("2005-01-03", periods=40)
    old = pd.Series(80.0, index=idx[:30])
    new = pd.Series(100.0, index=idx[20:])
    d = mf.dollar_log({"DTWEXM": old, "DTWEXBGS": new}, idx)
    assert np.allclose(np.exp(d.dropna()), 100.0)


def test_closes_drop_weekends_and_keep_bad_ohlc_rows():
    ts = pd.to_datetime(["2026-11-13", "2026-11-15", "2026-11-16"]).astype("int64") // 10**6
    rows = pd.DataFrame({"timestamp": ts, "open": [1, 2, 3], "high": [0.5, 2, 3], "low": [1, 2, 3], "close": [1, 2, 3]})
    s = mf.closes_from_rows(rows)
    assert [d.day for d in s.index] == [13, 16] and s.iloc[0] == 1
