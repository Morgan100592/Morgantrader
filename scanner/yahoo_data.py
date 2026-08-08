"""Yahoo Finance data feed (free, no API key) with caching + retries."""
from __future__ import annotations

import threading
import time
from typing import Dict, Optional, Tuple

import pandas as pd

try:
    import yfinance as yf
except ImportError:  # pragma: no cover
    yf = None

from config.settings import settings
from utils.helpers import get_logger

log = get_logger("scanner.yahoo")

# Morgantrader timeframe -> (yfinance interval, period)
TF_MAP: Dict[str, Tuple[str, str]] = {
    "M1": ("1m", "5d"),
    "M5": ("5m", "20d"),
    "M15": ("15m", "40d"),
    "M30": ("30m", "60d"),
    "H1": ("1h", "180d"),
    "H4": ("1h", "360d"),   # resampled from 1h
    "D1": ("1d", "3y"),
}

RESAMPLE_RULE = {"H4": "4h"}


class YahooDataFeed:
    """Fetches OHLCV candles from Yahoo Finance with a short-lived cache."""

    def __init__(self, cache_seconds: int = 45):
        self.cache_seconds = cache_seconds
        self._cache: Dict[str, Tuple[float, pd.DataFrame]] = {}
        self._lock = threading.Lock()
        if yf is None:
            log.error("yfinance is not installed. Run: pip install -r requirements.txt")

    # ------------------------------------------------------------------ utils
    @staticmethod
    def _normalise(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or len(df) == 0:
            return pd.DataFrame()
        if isinstance(df.columns, pd.MultiIndex):
            df = df.droplevel(1, axis=1)
        df = df.rename(columns={c: str(c).lower() for c in df.columns})
        keep = [c for c in ("open", "high", "low", "close", "volume") if c in df.columns]
        df = df[keep].copy()
        if "volume" not in df.columns:
            df["volume"] = 0.0
        df = df.dropna(subset=["open", "high", "low", "close"])
        df = df[~df.index.duplicated(keep="last")].sort_index()
        return df

    @staticmethod
    def _resample(df: pd.DataFrame, rule: str) -> pd.DataFrame:
        if df.empty:
            return df
        out = df.resample(rule, label="right", closed="right").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()
        return out

    def _download(self, ticker: str, interval: str, period: str) -> pd.DataFrame:
        if yf is None:
            return pd.DataFrame()
        last_err: Optional[Exception] = None
        for attempt in range(3):
            try:
                df = yf.download(
                    tickers=ticker,
                    interval=interval,
                    period=period,
                    auto_adjust=False,
                    progress=False,
                    threads=False,
                )
                df = self._normalise(df)
                if not df.empty:
                    return df
            except Exception as exc:  # network / rate limit
                last_err = exc
            time.sleep(1.5 * (attempt + 1))
        if last_err:
            log.warning("Yahoo download failed for %s %s: %s", ticker, interval, last_err)
        return pd.DataFrame()

    # ------------------------------------------------------------------- api
    def get_candles(self, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
        timeframe = timeframe.upper()
        interval, period = TF_MAP.get(timeframe, TF_MAP["M5"])
        key = f"{symbol}:{timeframe}"
        now = time.time()

        with self._lock:
            cached = self._cache.get(key)
            if cached and now - cached[0] < self.cache_seconds:
                return cached[1].tail(limit).copy()

        tickers = [settings.yahoo_ticker(symbol)] + settings.fallback_tickers(symbol)
        df = pd.DataFrame()
        for ticker in tickers:
            df = self._download(ticker, interval, period)
            if not df.empty:
                break

        if not df.empty and timeframe in RESAMPLE_RULE:
            df = self._resample(df, RESAMPLE_RULE[timeframe])

        with self._lock:
            self._cache[key] = (now, df)

        if df.empty:
            log.warning("No data returned for %s %s", symbol, timeframe)
        return df.tail(limit).copy()

    def get_price(self, symbol: str) -> Optional[float]:
        df = self.get_candles(symbol, "M5", limit=3)
        if df.empty:
            return None
        return float(df["close"].iloc[-1])

    def health_check(self) -> Dict[str, bool]:
        status = {}
        for symbol in settings.symbols:
            df = self.get_candles(symbol, "H1", limit=5)
            status[symbol] = not df.empty
        return status
