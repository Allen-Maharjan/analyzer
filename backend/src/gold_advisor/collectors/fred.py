"""FRED daily series via the public fredgraph CSV export (no API key)."""

import csv
import io
from datetime import date
from decimal import Decimal, InvalidOperation

import httpx

from gold_advisor.collectors.http import get_with_retries
from gold_advisor.collectors.types import MacroObservation, SourceSchemaError
from gold_advisor.domain import Source

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
MISSING = {"", "."}


def parse(series_id: str, text: str) -> list[MacroObservation]:
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    if header is None or len(header) != 2 or header[1].strip() != series_id:
        raise SourceSchemaError(f"fred {series_id}: unexpected header {header!r}")
    out: list[MacroObservation] = []
    for row in reader:
        if not row:
            continue
        if len(row) != 2:
            raise SourceSchemaError(f"fred {series_id}: malformed row {row!r}")
        raw_date, raw_value = row[0].strip(), row[1].strip()
        try:
            obs_date = date.fromisoformat(raw_date)
            value = None if raw_value in MISSING else Decimal(raw_value)
        except (ValueError, InvalidOperation) as exc:
            raise SourceSchemaError(f"fred {series_id}: bad row {row!r}") from exc
        out.append(MacroObservation(source=Source.FRED, series_id=series_id, obs_date=obs_date, value=value))
    return out


def fetch(client: httpx.Client, series_id: str, start: date) -> list[MacroObservation]:
    response = get_with_retries(client, URL, params={"id": series_id, "cosd": start.isoformat()})
    return parse(series_id, response.text)
