"""FENEGOSIDA public dashboard API (Federation of Nepal Gold and Silver Dealers' Association).

Endpoints were taken from the fenegosida.org frontend bundle and validated against live
responses on 2026-11-02. The ``*BaseRatePerGram`` field is misnamed by the source: the
value is the price for the unit written in ``rateType`` (1 tola or 10 grams).
"""

from collections import defaultdict
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError

from gold_advisor.collectors.http import get_with_retries, make_client
from gold_advisor.collectors.types import LocalMetalRate, SourceSchemaError
from gold_advisor.domain import (
    GRAMS_PER_UNIT,
    NEPAL_TZ,
    MassUnit,
    Metal,
    Purity,
    QualityFlag,
    Source,
)

BASE_URL = "https://api.fenegosida.org/api/website/v1/Dashboard"
TODAY_URL = f"{BASE_URL}/today"
MONTH_URL = f"{BASE_URL}/monthwisehistory"

LABELS: dict[str, tuple[Metal, Purity, MassUnit]] = {
    "छापावाल सुन (१ तोला)": (Metal.GOLD, Purity.HALLMARK, MassUnit.TOLA),
    "छापावाल सुन (१० ग्राम)": (Metal.GOLD, Purity.HALLMARK, MassUnit.TEN_GRAM),
    "असली चाँदी दर (१ तोला)": (Metal.SILVER, Purity.PURE_SILVER, MassUnit.TOLA),
    "असली चाँदी दर (१० ग्राम)": (Metal.SILVER, Purity.PURE_SILVER, MassUnit.TEN_GRAM),
}
REQUIRED_TODAY = (Metal.GOLD, Purity.HALLMARK, MassUnit.TOLA)
UNIT_RATIO_TOLERANCE = Decimal("0.003")


def make_fenegosida_client() -> httpx.Client:
    return make_client(headers={"Origin": "https://fenegosida.org", "Referer": "https://fenegosida.org/"})


class _TodayRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    todayDate: AwareDatetime
    yestardayDate: AwareDatetime | None = None
    rateType: str
    todayBaseRatePerGram: Decimal = Field(gt=0)
    yestardayBaseRatePerGram: Decimal | None = Field(default=None, gt=0)


class _HistoryRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: int
    todayDate: date
    rateType: str
    baseRatePerGram: Decimal = Field(gt=0)


def _rate(label: str, rate_date: date, published_at: datetime | None, price: Decimal) -> LocalMetalRate:
    metal, purity, unit = LABELS[label]
    return LocalMetalRate(
        source=Source.FENEGOSIDA,
        metal=metal,
        purity=purity,
        unit=unit,
        rate_date=rate_date,
        published_at=published_at,
        price_npr=price,
        source_label=label,
    )


def parse_today(payload: object) -> tuple[list[LocalMetalRate], list[str]]:
    if not isinstance(payload, list):
        raise SourceSchemaError("fenegosida today: expected a list")
    try:
        rows = [_TodayRow.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise SourceSchemaError(f"fenegosida today: unexpected row: {exc}") from exc

    rates: list[LocalMetalRate] = []
    notes: list[str] = []
    for row in rows:
        if row.rateType not in LABELS:
            notes.append(f"unknown rateType skipped: {row.rateType!r}")
            continue
        rates.append(
            _rate(row.rateType, row.todayDate.astimezone(NEPAL_TZ).date(), row.todayDate, row.todayBaseRatePerGram)
        )
        if row.yestardayDate is not None and row.yestardayBaseRatePerGram is not None:
            rates.append(
                _rate(
                    row.rateType,
                    row.yestardayDate.astimezone(NEPAL_TZ).date(),
                    row.yestardayDate,
                    row.yestardayBaseRatePerGram,
                )
            )
    if not rates:
        raise SourceSchemaError("fenegosida today: no recognized rate rows")
    return flag_unit_mismatches(rates), notes


def parse_history(payload: object) -> tuple[list[LocalMetalRate], list[str]]:
    if payload in ("", None):
        return [], []
    if not isinstance(payload, list):
        raise SourceSchemaError("fenegosida history: expected a list")
    try:
        rows = [_HistoryRow.model_validate(item) for item in payload]
    except ValidationError as exc:
        raise SourceSchemaError(f"fenegosida history: unexpected row: {exc}") from exc

    latest: dict[tuple[str, date], _HistoryRow] = {}
    notes: list[str] = []
    for row in sorted(rows, key=lambda r: r.id):
        if row.rateType not in LABELS:
            notes.append(f"unknown rateType skipped: {row.rateType!r}")
            continue
        latest[(row.rateType, row.todayDate)] = row  # higher id wins
    rates = [_rate(r.rateType, r.todayDate, None, r.baseRatePerGram) for r in latest.values()]
    return flag_unit_mismatches(rates), notes


def flag_unit_mismatches(rates: list[LocalMetalRate]) -> list[LocalMetalRate]:
    """Flag both rows when the tola and 10 g prices for the same day disagree beyond rounding."""
    groups: dict[tuple, dict[MassUnit, LocalMetalRate]] = defaultdict(dict)
    for r in rates:
        groups[(r.metal, r.purity, r.rate_date)][r.unit] = r
    bad: set[tuple] = set()
    for key, by_unit in groups.items():
        tola, ten = by_unit.get(MassUnit.TOLA), by_unit.get(MassUnit.TEN_GRAM)
        if tola is None or ten is None:
            continue
        expected = GRAMS_PER_UNIT[MassUnit.TOLA] / GRAMS_PER_UNIT[MassUnit.TEN_GRAM]
        if abs(tola.price_npr / ten.price_npr / expected - 1) > UNIT_RATIO_TOLERANCE:
            bad.add(key)
    return [
        replace(r, quality_flags=(QualityFlag.UNIT_MISMATCH,)) if (r.metal, r.purity, r.rate_date) in bad else r
        for r in rates
    ]


def fetch_today(client: httpx.Client) -> tuple[list[LocalMetalRate], list[str]]:
    return parse_today(get_with_retries(client, TODAY_URL).json())


def fetch_month(client: httpx.Client, month_start: date) -> tuple[list[LocalMetalRate], list[str]]:
    response = get_with_retries(client, MONTH_URL, params={"date": month_start.replace(day=1).isoformat()})
    return parse_history(response.json() if response.content else "")
