"""Swissquote public quote feed: backup live XAU/USD spot when Gold API fails.

No key or signup. The feed has no published terms, so it may change without notice;
any unexpected shape is treated as unavailable. The stored price is the bid/ask midpoint
of the tightest spread on the first platform listed.
"""

from gold_advisor.assets import AssetDefinition, GOLD

from datetime import datetime, timedelta
from decimal import Decimal

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from gold_advisor.collectors.http import get_with_retries
from gold_advisor.collectors.types import SourceSchemaError, SpotQuote
from gold_advisor.domain import UTC, Instrument, QualityFlag, Source

URL = "https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/XAU/USD"
MAX_CLOCK_SKEW = timedelta(seconds=60)


class _Price(BaseModel):
    model_config = ConfigDict(extra="ignore")
    bid: Decimal = Field(gt=0)
    ask: Decimal = Field(gt=0)


class _Platform(BaseModel):
    model_config = ConfigDict(extra="ignore")
    spreadProfilePrices: list[_Price] = Field(min_length=1)
    ts: int = Field(gt=0)


_PAYLOAD = TypeAdapter(list[_Platform])


def parse(payload: object, *, now: datetime, asset: AssetDefinition = GOLD) -> SpotQuote:
    try:
        platforms = _PAYLOAD.validate_python(payload)
    except ValidationError as exc:
        raise SourceSchemaError(f"swissquote: unexpected payload: {exc}") from exc
    if not platforms:
        raise SourceSchemaError("swissquote: empty payload")
    first = platforms[0]
    best = min(first.spreadProfilePrices, key=lambda p: p.ask - p.bid)
    if best.ask < best.bid:
        raise SourceSchemaError("swissquote: ask below bid")
    observed_at = datetime.fromtimestamp(first.ts / 1000, tz=UTC)
    return SpotQuote(
        source=Source.SWISSQUOTE,
        instrument=asset.instrument,
        observed_at=observed_at,
        price=(best.bid + best.ask) / 2,
        quality_flags=(QualityFlag.CLOCK_SKEW,) if observed_at - now > MAX_CLOCK_SKEW else (),
    )


def fetch(client: httpx.Client, *, now: datetime, asset: AssetDefinition = GOLD) -> SpotQuote:
    return parse(get_with_retries(client, f"https://forex-data-feed.swissquote.com/public-quotes/bboquotes/instrument/{asset.instrument}", attempts=2).json(), now=now, asset=asset)
