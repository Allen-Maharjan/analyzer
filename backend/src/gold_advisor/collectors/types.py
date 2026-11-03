"""Typed observations produced by collectors and consumed by persistence."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from gold_advisor.domain import Instrument, MassUnit, Metal, PriceSide, Purity, QualityFlag, Source, Timeframe


class SourceSchemaError(ValueError):
    """The source responded, but not in the shape we validated. Treat as unavailable."""


@dataclass(frozen=True)
class SpotQuote:
    source: Source
    instrument: str
    observed_at: datetime
    price: Decimal
    quality_flags: tuple[QualityFlag, ...] = ()


@dataclass(frozen=True)
class Candle:
    source: Source
    instrument: str
    timeframe: Timeframe
    bucket_start: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    price_side: PriceSide
    derived: bool = False
    component_count: int | None = None
    quality_flags: tuple[QualityFlag, ...] = ()

    @property
    def bucket_end(self) -> datetime:
        return self.bucket_start + self.timeframe.duration


@dataclass(frozen=True)
class LocalMetalRate:
    source: Source
    metal: Metal
    purity: Purity
    unit: MassUnit
    rate_date: date
    published_at: datetime | None  # None when the source only gives a date
    price_npr: Decimal
    source_label: str
    quality_flags: tuple[QualityFlag, ...] = ()


@dataclass(frozen=True)
class FxRate:
    source: Source
    currency: str
    rate_date: date
    unit: int
    buy: Decimal
    sell: Decimal
    published_at: datetime | None
    modified_at: datetime | None


@dataclass(frozen=True)
class MacroObservation:
    source: Source
    series_id: str
    obs_date: date
    value: Decimal | None  # None preserves a published gap (holiday, missing print)


@dataclass
class CollectionResult:
    inserted: int = 0
    revised: int = 0
    unchanged: int = 0
    notes: list[str] = field(default_factory=list)

    def add(self, other: "CollectionResult") -> None:
        self.inserted += other.inserted
        self.revised += other.revised
        self.unchanged += other.unchanged
        self.notes.extend(other.notes)
