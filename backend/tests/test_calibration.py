from datetime import date, timedelta

import pytest
from gold_advisor.analytics.calibration import Publication, evaluate


def series(count=400):
    start = date(2024, 1, 1)
    return [Publication(start + timedelta(days=i), 100 + (i % 8) * -0.3) for i in range(count)]


def test_chronological_holdout_and_baseline():
    result = evaluate(series(), minimum_windows=10)
    assert result.training_end < result.evaluation_start
    assert result.training.sample_size >= 10 and result.evaluation.sample_size >= 10
    assert result.baseline.sample_size == result.evaluation.sample_size
    assert result.baseline.mean_cost_vs_immediate == 0


def test_test_period_cannot_change_selected_threshold():
    original = series()
    first = evaluate(original, minimum_windows=10)
    changed = [Publication(p.day, p.price if p.day < first.evaluation_start else p.price * 1.5) for p in original]
    second = evaluate(changed, minimum_windows=10)
    assert first.threshold == second.threshold
    assert first.training == second.training


def test_missing_invalid_or_duplicate_data_rejected():
    with pytest.raises(ValueError):
        evaluate([], minimum_windows=1)
    data = series()
    with pytest.raises(ValueError):
        evaluate([*data, data[-1]])
    with pytest.raises(ValueError):
        evaluate([Publication(date(2024, 1, 1), float('nan'))])
