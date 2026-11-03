"""Shared domain vocabulary. Persisted values use the enum *values*, so never rename them."""

from datetime import timedelta
from decimal import Decimal
from enum import StrEnum
from zoneinfo import ZoneInfo

UTC = ZoneInfo("UTC")
NEPAL_TZ = ZoneInfo("Asia/Kathmandu")
NEW_YORK_TZ = ZoneInfo("America/New_York")

GRAMS_PER_TROY_OUNCE = Decimal("31.1034768")
GRAMS_PER_TOLA = Decimal("11.6638038")
# Spec-defined conversion for the reference price: XAU/USD x USD/NPR x 0.375 per tola.
TROY_OUNCES_PER_TOLA = Decimal("0.375")


class Source(StrEnum):
    GOLD_API = "gold_api"
    SWISSQUOTE = "swissquote"
    DUKASCOPY = "dukascopy"
    FENEGOSIDA = "fenegosida"
    NRB = "nrb"
    FRED = "fred"
    FEDERAL_RESERVE = "federal_reserve"


class Instrument(StrEnum):
    XAUUSD = "XAU/USD"
    XAGUSD = "XAG/USD"


class Metal(StrEnum):
    GOLD = "gold"
    SILVER = "silver"


class Purity(StrEnum):
    HALLMARK = "hallmark"  # छापावाल सुन
    FINE = "fine"  # तेजाबी सुन; not currently published by FENEGOSIDA
    PURE_SILVER = "pure_silver"  # असली चाँदी


class MassUnit(StrEnum):
    TOLA = "tola"
    TEN_GRAM = "10g"


GRAMS_PER_UNIT: dict[MassUnit, Decimal] = {
    MassUnit.TOLA: GRAMS_PER_TOLA,
    MassUnit.TEN_GRAM: Decimal(10),
}


class Timeframe(StrEnum):
    M15 = "15m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1D"
    W1 = "1W"

    @property
    def duration(self) -> timedelta:
        return _TIMEFRAME_DURATIONS[self]


_TIMEFRAME_DURATIONS = {
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
    Timeframe.W1: timedelta(weeks=1),
}

# Timeframes fetched from Dukascopy, and those derived from complete underlying bars.
COLLECTED_TIMEFRAMES = (Timeframe.M15, Timeframe.H1, Timeframe.D1)
DERIVED_TIMEFRAMES: dict[Timeframe, Timeframe] = {Timeframe.H4: Timeframe.H1, Timeframe.W1: Timeframe.D1}


class PriceSide(StrEnum):
    BID = "bid"
    MID = "mid"


class QualityFlag(StrEnum):
    CLOCK_SKEW = "clock_skew"  # source timestamp is in the future
    UNIT_MISMATCH = "unit_mismatch"  # tola and 10 g prices disagree
    PARTIAL_BUCKET = "partial_bucket"  # derived bar built from fewer underlying bars than a full session


class FreshnessStatus(StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MARKET_CLOSED = "market_closed"
    UNAVAILABLE = "unavailable"


class CollectorStatus(StrEnum):
    OK = "ok"
    FAILING = "failing"
    NEVER_RUN = "never_run"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class Decision(StrEnum):
    BUY = "BUY"
    WAIT = "WAIT"
    WATCH_CLOSELY = "WATCH CLOSELY"


class Outlook(StrEnum):
    BEARISH = "bearish"
    NEUTRAL = "neutral"
    BULLISH = "bullish"


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
