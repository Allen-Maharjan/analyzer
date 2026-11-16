"""Cross-checks between the two world-price sources (Gold API and Swissquote). Pure functions.

- Two fresh quotes from one run that differ by more than 0.5% are flagged SOURCES_DISAGREE, and the
  analysis treats that as an essential issue.
- A quote that moves more than 5% from the previous stored quote within 30 minutes is flagged
  UNCONFIRMED_JUMP unless the other source agrees with it within 0.5%. It is stored for audit but
  never used as the current price.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta

from gold_advisor.domain import QualityFlag

DISAGREE_PCT = 0.005
JUMP_PCT = 0.05
JUMP_WINDOW = timedelta(minutes=30)
# Two quotes count as "the same moment" for the disagreement check when this close in time.
PAIR_WINDOW = timedelta(minutes=10)


def differ(a: float, b: float, limit: float = DISAGREE_PCT) -> bool:
    return abs(a / b - 1) > limit


def unconfirmed_jump(
    price: float,
    observed_at: datetime,
    previous: tuple[float, datetime] | None,
    other: float | None,
) -> bool:
    if previous is None:
        return False
    prev_price, prev_at = previous
    if not timedelta(0) <= observed_at - prev_at <= JUMP_WINDOW:
        return False
    if not differ(price, prev_price, JUMP_PCT):
        return False
    return not (other is not None and not differ(price, other))


def flags(
    price: float,
    observed_at: datetime,
    previous: tuple[float, datetime] | None,
    other: tuple[float, datetime] | None,
) -> tuple[QualityFlag, ...]:
    """Flags for one new quote, given the previous usable stored quote and the other source's
    quote from the same run (None when that source failed)."""
    out: list[QualityFlag] = []
    paired = other is not None and abs(observed_at - other[1]) <= PAIR_WINDOW
    if paired and differ(price, other[0]):
        out.append(QualityFlag.SOURCES_DISAGREE)
    if unconfirmed_jump(price, observed_at, previous, other[0] if paired else None):
        out.append(QualityFlag.UNCONFIRMED_JUMP)
    return tuple(out)


def usable(quality_flags: Sequence[str]) -> bool:
    return QualityFlag.UNCONFIRMED_JUMP.value not in quality_flags
