"""Idempotent, revision-aware writes.

Re-collecting the same observation is a no-op. A changed value increments ``revision``;
for tables with history tracking the previous values are kept in ``observation_revisions``.
"""

from collections.abc import Sequence
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import Numeric, func, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from gold_advisor.collectors.types import (
    Candle,
    CollectionResult,
    FxRate,
    LocalMetalRate,
    MacroObservation,
    SpotQuote,
)
from gold_advisor.persistence.models import (
    Base,
    CandleRow,
    FxRateRow,
    LocalMetalRateRow,
    MacroObservationRow,
    ObservationRevisionRow,
    SpotQuoteRow,
)

BATCH_SIZE = 1000


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [_plain(v) for v in value]
    return value


def _row(obj: Any) -> dict[str, Any]:
    return {k: _plain(v) for k, v in asdict(obj).items()}


def _quantize(model: type[Base], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Round Decimals to the column scale so comparisons match what PostgreSQL stores."""
    scales = {
        c.name: Decimal(1).scaleb(-c.type.scale)
        for c in model.__table__.columns
        if isinstance(c.type, Numeric) and c.type.scale is not None
    }
    return [
        {k: (v.quantize(scales[k]) if k in scales and isinstance(v, Decimal) else v) for k, v in row.items()}
        for row in rows
    ]


def _json(value: Any) -> Any:
    if isinstance(value, (Decimal, date, datetime)):
        return str(value) if isinstance(value, Decimal) else value.isoformat()
    return value


def _batches(rows: list[dict[str, Any]]):
    for i in range(0, len(rows), BATCH_SIZE):
        yield rows[i : i + BATCH_SIZE]


def upsert_tracked(
    session: Session,
    model: type[Base],
    rows: list[dict[str, Any]],
    *,
    key_cols: Sequence[str],
    compare_cols: Sequence[str],
    coalesce_cols: Sequence[str] = (),
) -> CollectionResult:
    """Upsert with full history. ``coalesce_cols`` keep the stored value when the new one is null
    (for example a precise publication time that a date-only history endpoint lacks)."""
    result = CollectionResult()
    table = model.__table__
    tracked = list(compare_cols) + list(coalesce_cols)
    for batch in _batches(_quantize(model, rows)):
        keys = [tuple(r[k] for k in key_cols) for r in batch]
        key_expr = tuple_(*(table.c[k] for k in key_cols))
        existing = {
            tuple(row[k] for k in key_cols): row
            for row in session.execute(select(table).where(key_expr.in_(keys))).mappings()
        }
        new_rows: dict[tuple, dict[str, Any]] = {}
        for key, row in zip(keys, batch, strict=True):
            old = existing.get(key)
            if old is None:
                new_rows[key] = row  # later duplicates in one batch win
                continue
            current = {c: row[c] for c in compare_cols}
            current.update({c: row[c] if row[c] is not None else old[c] for c in coalesce_cols})
            if all(old[c] == current[c] for c in tracked):
                result.unchanged += 1
                continue
            session.add(
                ObservationRevisionRow(
                    table_name=table.name,
                    record_key={k: _json(old[k]) for k in key_cols},
                    previous={c: _json(old[c]) for c in tracked},
                    current={c: _json(current[c]) for c in tracked},
                )
            )
            session.execute(
                update(table)
                .where(key_expr == key)
                .values(**current, revision=table.c.revision + 1, updated_at=func.now())
            )
            result.revised += 1
        if new_rows:
            session.execute(insert(table).values(list(new_rows.values())))
            result.inserted += len(new_rows)
    return result


def save_spot_quote(session: Session, quote: SpotQuote) -> CollectionResult:
    stmt = (
        insert(SpotQuoteRow)
        .values(_quantize(SpotQuoteRow, [_row(quote)]))
        .on_conflict_do_nothing()
        .returning(SpotQuoteRow.observed_at)
    )
    inserted = len(session.execute(stmt).all())
    return CollectionResult(inserted=inserted, unchanged=1 - inserted)


def save_candles(session: Session, candles: list[Candle]) -> CollectionResult:
    """Bulk upsert without per-row history: a changed bar bumps ``revision`` and ``updated_at``."""
    result = CollectionResult()
    value_cols = ("open", "high", "low", "close", "volume", "component_count", "quality_flags")
    unique = {(c.source, c.instrument, c.timeframe, c.bucket_start): c for c in candles}
    for batch in _batches(_quantize(CandleRow, [_row(c) for c in unique.values()])):
        stmt = insert(CandleRow).values(batch)
        excluded = stmt.excluded
        table = CandleRow.__table__
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "instrument", "timeframe", "bucket_start"],
            set_={**{c: excluded[c] for c in value_cols}, "revision": table.c.revision + 1, "updated_at": func.now()},
            where=tuple_(*(table.c[c] for c in value_cols)).is_distinct_from(tuple_(*(excluded[c] for c in value_cols))),
        ).returning((table.c.revision == 0).label("inserted"))
        flags = [row.inserted for row in session.execute(stmt)]
        result.inserted += sum(flags)
        result.revised += len(flags) - sum(flags)
        result.unchanged += len(batch) - len(flags)
    return result


def save_local_rates(session: Session, rates: list[LocalMetalRate]) -> CollectionResult:
    return upsert_tracked(
        session,
        LocalMetalRateRow,
        [_row(r) for r in rates],
        key_cols=("source", "metal", "purity", "unit", "rate_date"),
        compare_cols=("price_npr", "source_label", "quality_flags"),
        coalesce_cols=("published_at",),
    )


def save_fx_rates(session: Session, rates: list[FxRate]) -> CollectionResult:
    return upsert_tracked(
        session,
        FxRateRow,
        [_row(r) for r in rates],
        key_cols=("source", "currency", "rate_date"),
        compare_cols=("unit", "buy", "sell", "published_at", "modified_at"),
    )


def save_macro(session: Session, observations: list[MacroObservation]) -> CollectionResult:
    return upsert_tracked(
        session,
        MacroObservationRow,
        [_row(o) for o in observations],
        key_cols=("source", "series_id", "obs_date"),
        compare_cols=("value",),
    )


def save_events(session: Session, events: list) -> CollectionResult:
    from gold_advisor.persistence.models import EconomicEventRow

    result = CollectionResult()
    for e in events:
        stmt = insert(EconomicEventRow).values(_row(e))
        stmt = stmt.on_conflict_do_update(
            index_elements=["source", "event_type", "scheduled_at"],
            set_={"title": stmt.excluded.title, "importance": stmt.excluded.importance},
            where=tuple_(EconomicEventRow.title, EconomicEventRow.importance).is_distinct_from(
                tuple_(stmt.excluded.title, stmt.excluded.importance)
            ),
        ).returning(EconomicEventRow.ingested_at)
        changed = len(session.execute(stmt).all())
        result.inserted += changed
        result.unchanged += 1 - changed
    return result
