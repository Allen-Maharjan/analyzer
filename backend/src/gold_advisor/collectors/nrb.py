"""Nepal Rastra Bank forex API (https://www.nrb.org.np/api-docs-v1/)."""

import time
from collections.abc import Iterator
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from gold_advisor.collectors.http import NRB_INTERMEDIATE, get_with_retries, make_client
from gold_advisor.collectors.types import FxRate, SourceSchemaError
from gold_advisor.domain import NEPAL_TZ, Source

URL = "https://www.nrb.org.np/api/forex/v1/rates"
PER_PAGE = 100
MAX_RANGE_DAYS = 90
PAUSE_BETWEEN_REQUESTS_SECONDS = 1.0


def make_nrb_client() -> httpx.Client:
    return make_client(extra_cert=NRB_INTERMEDIATE)


class _Currency(BaseModel):
    iso3: str
    unit: int = Field(gt=0)


class _Rate(BaseModel):
    currency: _Currency
    # Old publications contain null rates for some currencies; those days are skipped.
    buy: Decimal | None = Field(default=None, gt=0)
    sell: Decimal | None = Field(default=None, gt=0)


class _Day(BaseModel):
    model_config = ConfigDict(extra="ignore")
    date: date
    published_on: datetime | None = None
    modified_on: datetime | None = None
    rates: list[_Rate]

    @field_validator("date", mode="before")
    @classmethod
    def _fix_separator(cls, value: object) -> object:
        # NRB has at least one publication dated "2020-06.25".
        return value.replace(".", "-") if isinstance(value, str) else value


class _Pagination(BaseModel):
    page: int
    pages: int


class _Data(BaseModel):
    payload: list[_Day]


class _Response(BaseModel):
    model_config = ConfigDict(extra="ignore")
    data: _Data
    pagination: _Pagination


def _nepal_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=NEPAL_TZ) if value.tzinfo is None else value


def parse(payload: object, currencies: tuple[str, ...] = ("USD",)) -> tuple[list[FxRate], int]:
    """Return rates for the wanted currencies and the total page count."""
    try:
        body = _Response.model_validate(payload)
    except ValidationError as exc:
        raise SourceSchemaError(f"nrb: unexpected payload: {exc}") from exc
    rates = [
        FxRate(
            source=Source.NRB,
            currency=rate.currency.iso3,
            rate_date=day.date,
            unit=rate.currency.unit,
            buy=rate.buy,
            sell=rate.sell,
            published_at=_nepal_local(day.published_on),
            modified_at=_nepal_local(day.modified_on),
        )
        for day in body.data.payload
        for rate in day.rates
        if rate.currency.iso3 in currencies and rate.buy is not None and rate.sell is not None
    ]
    return rates, body.pagination.pages


def fetch_range(client: httpx.Client, start: date, end: date, *, sleep=time.sleep) -> Iterator[list[FxRate]]:
    """Yield rates one 90-day chunk at a time, oldest first, so callers can save as they go
    and an interrupted backfill resumes from the last saved date."""
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(end, chunk_start + timedelta(days=MAX_RANGE_DAYS - 1))
        page, pages, chunk = 1, 1, []
        while page <= pages:
            response = get_with_retries(
                client,
                URL,
                params={"from": chunk_start.isoformat(), "to": chunk_end.isoformat(), "per_page": PER_PAGE, "page": page},
                attempts=5,
                base_delay=3.0,
            )
            rates, pages = parse(response.json())
            chunk.extend(rates)
            page += 1
            sleep(PAUSE_BETWEEN_REQUESTS_SECONDS)
        yield chunk
        chunk_start = chunk_end + timedelta(days=1)
