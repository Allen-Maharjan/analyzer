from datetime import date, timedelta

import pytest

from gold_advisor.analytics.decision_evaluation import Observation, evaluate
from gold_advisor.domain import Decision


def test_recorded_buy_compared_with_immediate_and_minimum():
    start = date(2026, 1, 1)
    rows = [Observation(start + timedelta(days=i), 100 - i, Decision.BUY if i == 3 else Decision.WAIT)
            for i in range(8)]
    result = evaluate(rows, minimum_windows=1)
    assert result.windows == 1 and result.buys == 1
    assert evaluate(rows).status == "insufficient"
    assert evaluate(rows).mean_cost_vs_immediate is None
    assert result.mean_cost_vs_immediate == pytest.approx(-0.03)
    assert result.mean_regret == pytest.approx(97 / 93 - 1)
    assert result.mean_baseline_regret == pytest.approx(100 / 93 - 1)


def test_incomplete_or_gapped_windows_are_not_scored():
    start = date(2026, 1, 1)
    assert evaluate([Observation(start, 100, Decision.BUY)]).windows == 0
    rows = [Observation(start, 100, Decision.BUY), Observation(start + timedelta(days=7), 90, Decision.WAIT)]
    assert evaluate(rows).windows == 0


def test_rejects_unsorted_or_invalid_prices():
    d = date(2026, 1, 1)
    with pytest.raises(ValueError):
        evaluate([Observation(d, 100, Decision.BUY), Observation(d, 90, Decision.WAIT)])
    with pytest.raises(ValueError):
        evaluate([Observation(d, -1, Decision.WAIT)])
