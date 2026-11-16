from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

from gold_advisor.analytics import position
from gold_advisor.decision import split
from gold_advisor.domain import NEPAL_TZ, UTC, Decision, Outlook

NOW = datetime(2026, 11, 16, 14, 0, tzinfo=NEPAL_TZ).astimezone(UTC)


def test_buy_splits_only_in_a_falling_market():
    assert split.reason_for(Decision.BUY, Outlook.BEARISH, False)
    assert split.reason_for(Decision.BUY, Outlook.NEUTRAL, True)  # paused breakdown
    assert split.reason_for(Decision.BUY, Outlook.BULLISH, False) is None
    assert split.reason_for(Decision.WAIT, Outlook.BEARISH, False) is None


def test_deadline_is_the_day_before_the_next_announcement_or_a_week():
    cpi = datetime(2026, 11, 20, 13, 30, tzinfo=UTC)
    assert split.deadline(NOW, [(cpi, "US inflation report (CPI)")]) == (date(2026, 11, 19), "the day before the US inflation report (CPI)")
    far = NOW + timedelta(days=20)
    assert split.deadline(NOW, [(far, "FOMC")])[0] == date(2026, 11, 23)


def test_second_half_reports_the_trigger_that_was_reached():
    first = NOW - timedelta(days=1)
    assert split.second_half(first, 270000, 267500, 275500, date(2026, 11, 20), 267000, NOW).reached == "dip"
    assert split.second_half(first, 270000, 267500, 275500, date(2026, 11, 20), 276000, NOW).reached == "recovery"
    assert split.second_half(first, 270000, 267500, 275500, date(2026, 11, 16), 270000, NOW).reached == "deadline"
    waiting = split.second_half(first, 270000, 267500, 275500, date(2026, 11, 20), 270000, NOW)
    assert waiting.reached is None and "Rs 2,67,500" in waiting.plain


def test_key_levels_are_world_level_times_the_snapshot_factor_and_skip_near_duplicates():
    levels = {
        "1D": [{"id": "1D-3950", "price": 3950.0, "touches": 2}, {"id": "1D-4100", "price": 4100.0, "touches": 3}],
        "4h": [{"id": "4h-3955", "price": 3955.0, "touches": 1}, {"id": "4h-3900", "price": 3900.0, "touches": 1},
               {"id": "4h-4200", "price": 4200.0, "touches": 1}],
    }
    states = {"1D": [{"level_id": "1D-3950", "state": "touch"}]}
    keys = position.key_levels(levels, states, 4000.0, 68.5, 500)
    assert [(k.kind, k.world_price) for k in keys] == [("floor", 3950.0), ("floor", 3900.0), ("ceiling", 4100.0), ("ceiling", 4200.0)]
    assert keys[0].rupees == round(3950 * 68.5 / 500) * 500 and keys[0].state == "touch"


def test_position_sentence_uses_rupees_and_the_window_start():
    hist = [(date(2026, 10, 1) + timedelta(days=i), 270000.0 + 100 * i) for i in range(30)]
    idx = pd.date_range(end=datetime(2026, 11, 15, tzinfo=UTC), periods=400, freq="1D")
    low = np.linspace(3000, 4000, 400)
    d1 = pd.DataFrame({"open": low, "high": low + 10, "low": low, "close": low + 5}, index=idx)
    pos = position.position("Gold", hist, d1, 4100.0, NOW)
    assert pos.above_low_npr == 2900 and pos.below_high_npr == 0
    assert pos.plain.startswith("Gold in Nepal is at its highest price since 1 Oct.")
    assert pos.days_since_52w_low is None and pos.world_52w_low < pos.world_52w_high  # rising: no new low this year
    falling = d1.iloc[::-1].set_axis(d1.index)
    assert position.position("Gold", hist, falling, 3000.0, NOW).days_since_52w_low == 0
