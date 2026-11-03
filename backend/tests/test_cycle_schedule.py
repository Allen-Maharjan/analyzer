from datetime import datetime

import pytest

from gold_advisor.assets import GOLD
from gold_advisor.cycle import world_market_active
from gold_advisor.domain import UTC


@pytest.mark.parametrize(
    ("utc", "active"),
    [
        ("2026-11-06T21:45", True),   # Friday, before the 17:00 New York close
        ("2026-11-06T22:45", True),   # just closed: still collect the closing candles
        ("2026-11-06T23:15", False),  # Friday evening, closed for the weekend
        ("2026-11-07T10:00", False),  # Saturday
        ("2026-11-08T12:00", False),  # Sunday, before the 18:00 New York open
        ("2026-11-08T23:15", True),   # Sunday evening New York: reopened
        ("2026-11-04T06:45", True),   # ordinary weekday
    ],
)
def test_world_prices_collected_only_while_market_is_active(utc, active):
    now = datetime.fromisoformat(utc).replace(tzinfo=UTC)
    assert world_market_active(GOLD, now) is active
