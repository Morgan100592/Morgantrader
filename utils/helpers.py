"""Shared helpers: logging, formatting, risk math, tiny JSON persistence."""
from __future__ import annotations

import json
import logging
import math
import os
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict

from config.settings import settings

_LOG_CONFIGURED = False
_LOCK = threading.Lock()


def setup_logging(level: str | None = None) -> None:
    global _LOG_CONFIGURED
    with _LOCK:
        if _LOG_CONFIGURED:
            return
        lvl = getattr(logging, (level or settings.log_level).upper(), logging.INFO)
        root = logging.getLogger()
        root.setLevel(lvl)
        fmt = logging.Formatter(
            "%(asctime)s | %(levelname)-7s | %(name)-22s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)
        try:
            fileh = RotatingFileHandler(settings.log_file, maxBytes=2_000_000, backupCount=3)
            fileh.setFormatter(fmt)
            root.addHandler(fileh)
        except OSError:
            pass
        for noisy in ("urllib3", "yfinance", "peewee", "werkzeug", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)
        _LOG_CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def round_price(symbol: str, price: float) -> float:
    return round(safe_float(price), settings.digits(symbol))


def fmt_price(symbol: str, price: float) -> str:
    return f"{round_price(symbol, price):.{settings.digits(symbol)}f}"


def pips_between(symbol: str, a: float, b: float) -> float:
    size = settings.pip_size(symbol)
    if size <= 0:
        return 0.0
    return abs(safe_float(a) - safe_float(b)) / size


def pct(part: float, whole: float) -> float:
    whole = safe_float(whole)
    if whole == 0:
        return 0.0
    return round(safe_float(part) / whole * 100.0, 2)


def calc_lot_size(symbol: str, entry: float, stop_loss: float, tier: str,
                  balance: float | None = None) -> Dict[str, float]:
    """Position size from % account risk, ATR stop distance and pip value."""
    balance = safe_float(balance if balance is not None else settings.account_balance, 1000.0)
    risk_pct = settings.risk_for_tier(tier)
    risk_amount = balance * risk_pct / 100.0
    sl_pips = pips_between(symbol, entry, stop_loss)
    pip_val = settings.pip_value(symbol)
    if sl_pips <= 0 or pip_val <= 0:
        lots = 0.01
    else:
        lots = risk_amount / (sl_pips * pip_val)
    lots = max(0.01, round(lots, 2))
    return {
        "lots": lots,
        "risk_percent": risk_pct,
        "risk_amount": round(risk_amount, 2),
        "sl_pips": round(sl_pips, 1),
        "balance": round(balance, 2),
    }


class JsonStore:
    """Thread-safe tiny JSON file store (signal history, stats)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def read(self, default: Any = None) -> Any:
        if default is None:
            default = []
        with self._lock:
            if not self.path.exists():
                return default
            try:
                with open(self.path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                return default

    def write(self, data: Any) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            try:
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(data, fh, indent=2, default=str)
                os.replace(tmp, self.path)
            except OSError:
                pass

    def append(self, item: Any, max_items: int = 2000) -> None:
        data = self.read([])
        if not isinstance(data, list):
            data = []
        data.append(item)
        self.write(data[-max_items:])
