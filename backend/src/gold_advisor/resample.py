"""Derive 4-hour and weekly bars from complete underlying bars.

Buckets are UTC-aligned: 4-hour buckets start at 00/04/08/12/16/20 UTC; weekly buckets
start Sunday 00:00 UTC so the Sunday evening session belongs to its trading week.
A derived bar is emitted only once its bucket has ended and the underlying data is known
to be complete through that end, so a late-arriving hourly bar cannot be silently missed.
"""

from collections import defaultdict
from datetime import datetime, timedelta

from gold_advisor.collectors.types import Candle
from gold_advisor.domain import DERIVED_TIMEFRAMES, QualityFlag, Timeframe

_EPOCH_SUNDAY_OFFSET = timedelta(days=4)  # 1970-01-01 was a Thursday; 1969-12-28 a Sunday
FULL_COMPONENT_COUNT = {Timeframe.H4: 4, Timeframe.W1: 5}


def bucket_start(at: datetime, timeframe: Timeframe) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=at.tzinfo)
    if timeframe is Timeframe.W1:
        epoch -= _EPOCH_SUNDAY_OFFSET
    elapsed = at - epoch
    return epoch + (elapsed // timeframe.duration) * timeframe.duration


def derive(underlying: list[Candle], target: Timeframe, complete_through: datetime) -> list[Candle]:
    source_tf = DERIVED_TIMEFRAMES[target]
    groups: dict[datetime, list[Candle]] = defaultdict(list)
    for bar in underlying:
        if bar.timeframe is not source_tf:
            raise ValueError(f"expected {source_tf} bars to derive {target}, got {bar.timeframe}")
        if bar.bucket_end <= complete_through:
            groups[bucket_start(bar.bucket_start, target)].append(bar)

    derived: list[Candle] = []
    for start, bars in sorted(groups.items()):
        if start + target.duration > complete_through:
            continue
        bars.sort(key=lambda b: b.bucket_start)
        first = bars[0]
        volumes = [b.volume for b in bars]
        partial = len(bars) < FULL_COMPONENT_COUNT[target]
        derived.append(
            Candle(
                source=first.source,
                instrument=first.instrument,
                timeframe=target,
                bucket_start=start,
                open=first.open,
                high=max(b.high for b in bars),
                low=min(b.low for b in bars),
                close=bars[-1].close,
                volume=None if any(v is None for v in volumes) else sum(volumes),
                price_side=first.price_side,
                derived=True,
                component_count=len(bars),
                quality_flags=(QualityFlag.PARTIAL_BUCKET,) if partial else (),
            )
        )
    return derived
