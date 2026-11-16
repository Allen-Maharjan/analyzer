from datetime import datetime, timedelta

from gold_advisor import quotes
from gold_advisor.domain import UTC, QualityFlag

T = datetime(2026, 11, 16, 6, 0, tzinfo=UTC)


def test_sources_more_than_half_a_percent_apart_disagree():
    assert quotes.flags(4000, T, None, (4025, T)) == (QualityFlag.SOURCES_DISAGREE,)
    assert quotes.flags(4000, T, None, (4015, T)) == ()
    assert quotes.flags(4000, T, None, (4025, T - timedelta(hours=1))) == ()  # not the same moment


def test_unconfirmed_jump_is_rejected_and_a_confirmed_one_is_kept():
    previous = (4000.0, T - timedelta(minutes=10))
    assert QualityFlag.UNCONFIRMED_JUMP in quotes.flags(4250, T, previous, None)
    assert quotes.flags(4250, T, previous, (4245, T)) == ()
    assert quotes.flags(4250, T, (4000.0, T - timedelta(hours=2)), None) == ()  # previous too old to compare
    assert not quotes.usable([QualityFlag.UNCONFIRMED_JUMP.value])
