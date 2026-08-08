"""Multi-timeframe market data bundle for a symbol."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import pandas as pd

from config.settings import settings
from scanner.yahoo_data import YahooDataFeed
from utils.helpers import get_logger

log = get_logger("scanner.market_data")

MIN_CANDLES = 60


@dataclass
class MarketSnapshot:
    symbol: str
    frames: Dict[str, pd.DataFrame] = field(default_factory=dict)
    price: float = 0.0

    @property
    def ok(self) -> bool:
        required = [settings.tf_primary, settings.tf_confirm, settings.tf_trend]
        return all(
            tf in self.frames and len(self.frames[tf]) >= MIN_CANDLES for tf in required
        )

    def frame(self, timeframe: str) -> pd.DataFrame:
        return self.frames.get(timeframe.upper(), pd.DataFrame())


class MarketData:
    """Loads M5 / M15 / H1 (+ optional H4) candles for each symbol."""

    def __init__(self, feed: Optional[YahooDataFeed] = None):
        self.feed = feed or YahooDataFeed()

    def timeframes(self) -> list:
        tfs = [settings.tf_primary, settings.tf_confirm, settings.tf_trend]
        if settings.use_h4:
            tfs.append(settings.tf_optional)
        return tfs

    def load(self, symbol: str, limit: int = 500) -> MarketSnapshot:
        snap = MarketSnapshot(symbol=symbol)
        for tf in self.timeframes():
            df = self.feed.get_candles(symbol, tf, limit=limit)
            if not df.empty:
                snap.frames[tf.upper()] = df
        primary = snap.frame(settings.tf_primary)
        if not primary.empty:
            snap.price = float(primary["close"].iloc[-1])
        if not snap.ok:
            log.debug("Incomplete data for %s (frames=%s)", symbol, list(snap.frames))
        return snap

    def load_all(self, symbols: Optional[list] = None) -> Dict[str, MarketSnapshot]:
        return {s: self.load(s) for s in (symbols or settings.symbols)}
