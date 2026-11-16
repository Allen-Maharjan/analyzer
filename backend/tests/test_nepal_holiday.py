"""rules-6: a Nepal holiday (source answers, nothing new) still gets a rule-based verdict.

Real sequence, Tihar 2026: FENEGOSIDA published gold Rs 2,84,300 on 9 Nov, then nothing until
Rs 2,71,700 on 13 Nov, while the collector kept succeeding.
"""

from datetime import date, datetime, timedelta

import pytest

from gold_advisor import freshness, health
from gold_advisor.analysis import _essential_issues
from gold_advisor.assets import GOLD
from gold_advisor.decision.nepal import AlignedPublication
from gold_advisor.decision.rules import decide
from gold_advisor.domain import NEPAL_TZ, UTC, CollectorStatus, FreshnessStatus, Source
from test_decision_rules import inputs, lag

LAST_PUBLICATION = date(2026, 11, 9)


def _datasets(now: datetime, collector_success: datetime) -> dict[str, health.DatasetHealth]:
    collector = health.CollectorHealth(CollectorStatus.OK, collector_success, None, None, 0)
    fresh = freshness.Freshness(FreshnessStatus.FRESH, "ok")
    nepal = freshness.nepal_publication(LAST_PUBLICATION, now, collector_success)
    return {
        GOLD.local_dataset: health.DatasetHealth(GOLD.local_dataset, Source.FENEGOSIDA, LAST_PUBLICATION, nepal, collector),
        "usd_npr": health.DatasetHealth("usd_npr", Source.NRB, now.date(), fresh, collector),
        "xauusd_candles_4h": health.DatasetHealth("xauusd_candles_4h", Source.DUKASCOPY, now, fresh, collector),
    }


def _verdict(now: datetime, collector_success: datetime):
    datasets = _datasets(now, collector_success)
    nepal = datasets[GOLD.local_dataset]
    latest = AlignedPublication(LAST_PUBLICATION, datetime(2026, 11, 9, 4, 27, tzinfo=UTC), True, 284300, 4000, 141.5, 212250, 0.339)
    return nepal, decide(inputs(
        essential_issues=_essential_issues(datasets, "gold_api live spot", [], GOLD),
        lag=lag(latest=latest),
        nepal_quiet_since=nepal.latest_observation if nepal.freshness.status is FreshnessStatus.NOT_PUBLISHED else None,
    ))


@pytest.mark.parametrize("day", [10, 11, 12])
def test_holiday_with_healthy_collector_gets_a_rule_based_verdict(day):
    now = datetime(2026, 11, day, 14, 0, tzinfo=NEPAL_TZ).astimezone(UTC)
    nepal, result = _verdict(now, now - timedelta(minutes=5))
    assert nepal.freshness.status is FreshnessStatus.NOT_PUBLISHED
    assert result.rule != "data"
    assert any("not published a new price since 9 Nov" in line for line in result.limitations)


def test_failed_collector_still_means_data():
    now = datetime(2026, 11, 11, 14, 0, tzinfo=NEPAL_TZ).astimezone(UTC)
    nepal, result = _verdict(now, now - timedelta(hours=5))  # last success long ago: the collector is failing
    assert nepal.freshness.status is FreshnessStatus.STALE
    assert result.rule == "data"


def test_week_long_silence_is_a_data_problem_again():
    now = datetime(2026, 11, 17, 14, 0, tzinfo=NEPAL_TZ).astimezone(UTC)
    assert freshness.nepal_publication(LAST_PUBLICATION, now, now - timedelta(minutes=5)).status is FreshnessStatus.STALE
