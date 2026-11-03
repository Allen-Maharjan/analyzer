"""Asset definitions are the authoritative provider and presentation configuration.

Instrument identifiers are data, not an enum of every possible exchange listing.
A future equity adapter supplies its own calendar and analysis profile.
"""
from dataclasses import dataclass
from gold_advisor.domain import Metal, Purity, Source, Timeframe
from gold_advisor.market import is_xau_open, last_open_instant
from collections.abc import Callable
from datetime import datetime

@dataclass(frozen=True)
class MarketCalendar:
    is_open: Callable[[datetime], bool]
    last_open: Callable[[datetime], datetime]

METALS_CALENDAR = MarketCalendar(is_xau_open, last_open_instant)

@dataclass(frozen=True)
class AssetDefinition:
    id: str
    label: str
    instrument: str
    quote_currency: str
    price_unit: str
    candle_source: Source
    calendar: MarketCalendar
    timeframes: tuple[Timeframe, ...]
    analysis_profile: str
    price_side: str = "bid"
    bucket_alignment: str = "UTC; daily bars close at 00:00 UTC; weekly bars start Sunday 00:00 UTC"
    spot_symbol: str | None = None
    candle_symbol: str | None = None
    metal: Metal | None = None
    purity: Purity | None = None
    local_label: str | None = None
    watch_levels: tuple[float, ...] = ()
    buy_drop_rupees: float | None = None
    buy_drop_pct: float = -0.01
    # BUY also counts a slide that built up over a few weeks: the latest Nepal price at least this far
    # below its highest of the last 20 publications. None turns the check off. Tuned on a two-year
    # replay (Dec 2024 to Nov 2026): it improved gold's BUY timing; for silver it made it worse, so it is off.
    buy_drawdown_pct: float | None = None
    # Don't say BUY when Nepal's next price is expected at least this much lower (say WAIT instead).
    # Walk-forward tested: a small improvement in both years for both metals. None turns it off.
    buy_block_expected_drop_pct: float | None = -0.005
    # FENEGOSIDA publishes gold in whole hundreds and silver in fives; forecasts are rounded the same way.
    nepal_price_step: float = 5.0
    wait_decline_pct: float = -0.02
    # News search (FreeNewsAPI in_title phrases) and the words a headline must contain.
    news_terms: tuple[str, ...] = ()
    news_keywords: tuple[str, ...] = ()

    @property
    def dataset_prefix(self) -> str:
        return self.instrument.replace('/', '').lower()

    @property
    def local_dataset(self) -> str:
        return f"nepal_{self.metal}_{self.purity}_tola"

    def job(self, name: str) -> str:
        # Preserve historical gold collector identities.
        return name if self.id == 'gold' else f"{name}.{self.id}"

    @property
    def watch_key(self) -> str:
        return f"watch_levels:{self.id}"

    def public(self) -> dict:
        return {"id": self.id, "label": self.label, "instrument": self.instrument,
                "quote_currency": self.quote_currency, "price_unit": self.price_unit,
                "local_label": self.local_label, "timeframes": list(self.timeframes)}

ASSETS = {
    a.id: a for a in (
        AssetDefinition('gold', 'Gold', 'XAU/USD', 'USD', 'ounce', Source.DUKASCOPY,
                        METALS_CALENDAR, tuple(Timeframe), 'nepal_metal', spot_symbol='XAU', candle_symbol='xauusd',
                        metal=Metal.GOLD, purity=Purity.HALLMARK, local_label='Hallmark gold', watch_levels=(4000.0,), buy_drop_rupees=-3000, buy_drawdown_pct=-0.05, nepal_price_step=100.0,
                        news_terms=('gold price', 'gold bullion', 'XAU USD'), news_keywords=('gold', 'xau', 'bullion', 'precious metal')),
        AssetDefinition('silver', 'Silver', 'XAG/USD', 'USD', 'ounce', Source.DUKASCOPY,
                        METALS_CALENDAR, tuple(Timeframe), 'nepal_metal', spot_symbol='XAG', candle_symbol='xagusd',
                        metal=Metal.SILVER, purity=Purity.PURE_SILVER, local_label='Pure silver',
                        news_terms=('silver price', 'silver bullion', 'XAG USD'), news_keywords=('silver', 'xag', 'bullion', 'precious metal')),
    )
}
GOLD = ASSETS['gold']

def get_asset(identifier: str) -> AssetDefinition:
    try:
        return ASSETS[identifier]
    except KeyError as error:
        raise ValueError(f"Unknown asset: {identifier}") from error
