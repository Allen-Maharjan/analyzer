"""Gold API free spot endpoint (https://gold-api.com)."""

from gold_advisor.assets import AssetDefinition, GOLD

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from gold_advisor.collectors.http import get_with_retries
from gold_advisor.collectors.types import SourceSchemaError, SpotQuote
from gold_advisor.domain import UTC, Instrument, QualityFlag, Source

URL = "https://api.gold-api.com/price/XAU"
MAX_CLOCK_SKEW = timedelta(seconds=60)


class _Payload(BaseModel):
    model_config = ConfigDict(extra="ignore")
    symbol: str
    currency: Literal["USD"]
    price: Decimal = Field(gt=0)
    updatedAt: AwareDatetime


def parse(payload: object, *, now: datetime, asset: AssetDefinition = GOLD) -> SpotQuote:
    try:
        data = _Payload.model_validate(payload)
    except ValidationError as exc:
        raise SourceSchemaError(f"gold_api: unexpected payload: {exc}") from exc
    if data.symbol != asset.spot_symbol:
        raise SourceSchemaError("gold_api: symbol does not match requested asset")
    observed_at = data.updatedAt.astimezone(UTC)
    flags = (QualityFlag.CLOCK_SKEW,) if observed_at - now > MAX_CLOCK_SKEW else ()
    return SpotQuote(
        source=Source.GOLD_API,
        instrument=asset.instrument,
        observed_at=observed_at,
        price=data.price,
        quality_flags=flags,
    )


def fetch(client: httpx.Client, *, now: datetime, asset: AssetDefinition = GOLD) -> SpotQuote:
    return parse(get_with_retries(client, f"https://api.gold-api.com/price/{asset.spot_symbol}").json(), now=now, asset=asset)
