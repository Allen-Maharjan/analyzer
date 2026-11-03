"""Dukascopy XAU/USD history via the pinned ``dukascopy-node`` package (bid prices).

The Node script is invoked without a shell and with fixed, validated arguments.
"""

from gold_advisor.assets import AssetDefinition, GOLD

import json
import subprocess
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from gold_advisor.collectors.types import Candle, SourceSchemaError
from gold_advisor.config import get_settings
from gold_advisor.domain import UTC, Instrument, PriceSide, Source, Timeframe

_DUKASCOPY_TIMEFRAME = {Timeframe.M15: "m15", Timeframe.H1: "h1", Timeframe.D1: "d1"}


class DukascopyError(RuntimeError):
    pass


class _Row(BaseModel):
    timestamp: int = Field(gt=0)
    open: Decimal = Field(gt=0)
    high: Decimal = Field(gt=0)
    low: Decimal = Field(gt=0)
    close: Decimal = Field(gt=0)
    volume: Decimal | None = Field(default=None, ge=0)


_ROWS = TypeAdapter(list[_Row])


def parse(raw: str, timeframe: Timeframe, *, now: datetime, asset: AssetDefinition = GOLD) -> list[Candle]:
    """Parse script output, keeping only bars whose period has fully elapsed."""
    try:
        rows = _ROWS.validate_json(raw)
    except ValidationError as exc:
        raise SourceSchemaError(f"dukascopy {timeframe}: unexpected output: {exc}") from exc
    candles: list[Candle] = []
    for row in rows:
        if not (row.low <= min(row.open, row.close) and row.high >= max(row.open, row.close)):
            raise SourceSchemaError(f"dukascopy {timeframe}: inconsistent OHLC at {row.timestamp}")
        bucket_start = datetime.fromtimestamp(row.timestamp / 1000, tz=UTC)
        if bucket_start + timeframe.duration > now:
            continue
        candles.append(
            Candle(
                source=Source.DUKASCOPY,
                instrument=asset.instrument,
                timeframe=timeframe,
                bucket_start=bucket_start,
                open=row.open,
                high=row.high,
                low=row.low,
                close=row.close,
                volume=row.volume,
                price_side=PriceSide.BID,
            )
        )
    return candles


def fetch(timeframe: Timeframe, start: datetime, end: datetime, *, now: datetime, asset: AssetDefinition = GOLD) -> list[Candle]:
    if timeframe not in _DUKASCOPY_TIMEFRAME:
        raise ValueError(f"Dukascopy collection does not support {timeframe}")
    settings = get_settings()
    args = json.dumps(
        {
            "instrument": asset.candle_symbol,
            "timeframe": _DUKASCOPY_TIMEFRAME[timeframe],
            "from": start.astimezone(UTC).isoformat(),
            "to": end.astimezone(UTC).isoformat(),
        }
    )
    try:
        completed = subprocess.run(
            [settings.node_binary, str(settings.dukascopy_script), args],
            capture_output=True,
            text=True,
            timeout=settings.dukascopy_timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DukascopyError(f"dukascopy {timeframe}: timed out") from exc
    if completed.returncode != 0:
        raise DukascopyError(f"dukascopy {timeframe}: exit {completed.returncode}: {completed.stderr.strip()[:500]}")
    return parse(completed.stdout, timeframe, now=now, asset=asset)
