"""Technical indicators per timeframe, computed with TA-Lib over completed bars only.

Values stay NaN (null in output) during each indicator's warm-up period. Missing bars are
not filled: indicators run over the bars that exist.
"""

import numpy as np
import pandas as pd
import talib

from gold_advisor.domain import Timeframe

VERSION = "indicators-2"
SMA_PERIODS = (20, 50, 100, 200)
EMA_PERIODS = (9, 21, 50, 200)
RSI_PERIOD = 14
MACD = (12, 26, 9)
BBANDS = (20, 2.0)
ATR_PERIOD = 14
REALIZED_VOL_WINDOW = 20
BARS_PER_YEAR = {
    Timeframe.M15: 252 * 23 * 4,
    Timeframe.H1: 252 * 23,
    Timeframe.H4: 252 * 6,
    Timeframe.D1: 252,
    Timeframe.W1: 52,
}


def compute(bars: pd.DataFrame, timeframe: Timeframe) -> pd.DataFrame:
    """``bars`` has float columns open/high/low/close, sorted by a UTC ``bucket_start`` index."""
    o, h, l, c = (bars[col].to_numpy(dtype=float) for col in ("open", "high", "low", "close"))
    out = pd.DataFrame(index=bars.index)
    out["open"], out["high"], out["low"], out["close"] = o, h, l, c
    for p in SMA_PERIODS:
        out[f"sma_{p}"] = talib.SMA(c, timeperiod=p)
    for p in EMA_PERIODS:
        out[f"ema_{p}"] = talib.EMA(c, timeperiod=p)
    out["rsi_14"] = talib.RSI(c, timeperiod=RSI_PERIOD)
    macd, signal, hist = talib.MACD(c, fastperiod=MACD[0], slowperiod=MACD[1], signalperiod=MACD[2])
    out["macd"], out["macd_signal"], out["macd_hist"] = macd, signal, hist
    upper, middle, lower = talib.BBANDS(c, timeperiod=BBANDS[0], nbdevup=BBANDS[1], nbdevdn=BBANDS[1])
    out["bb_upper"], out["bb_middle"], out["bb_lower"] = upper, middle, lower
    out["atr_14"] = talib.ATR(h, l, c, timeperiod=ATR_PERIOD)
    out["stoch_k"], out["stoch_d"] = talib.STOCH(h, l, c, fastk_period=14, slowk_period=3, slowd_period=3)
    out["adx_14"] = talib.ADX(h, l, c, timeperiod=14)
    out["plus_di"] = talib.PLUS_DI(h, l, c, timeperiod=14)
    out["minus_di"] = talib.MINUS_DI(h, l, c, timeperiod=14)
    log_ret = np.log(out["close"]).diff()
    out["return_1"] = out["close"].pct_change()
    out["realized_vol"] = log_ret.rolling(REALIZED_VOL_WINDOW).std() * np.sqrt(BARS_PER_YEAR[timeframe])
    return out


def latest_values(ind: pd.DataFrame) -> dict[str, float | None]:
    if ind.empty:
        return {}
    row = ind.iloc[-1]
    return {k: (None if pd.isna(v) else round(float(v), 4)) for k, v in row.items()}
