"""Central configuration for Morgantrader."""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):
        return False

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

# Load .env from config/ first, then project root (root wins if present).
load_dotenv(BASE_DIR / "config" / ".env")
load_dotenv(BASE_DIR / ".env", override=True)


def _bool(key: str, default: bool = False) -> bool:
    return str(os.getenv(key, str(default))).strip().lower() in ("1", "true", "yes", "on")


def _int(key: str, default: int) -> int:
    try:
        return int(float(os.getenv(key, default)))
    except (TypeError, ValueError):
        return default


def _float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


# Internal symbol -> Yahoo Finance ticker
SYMBOL_MAP: Dict[str, str] = {
    "XAUUSD": "XAUUSD=X",
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "GBPJPY": "GBPJPY=X",
    "EURJPY": "EURJPY=X",
    "GBPAUD": "GBPAUD=X",
    "NZDUSD": "NZDUSD=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
    "BTCUSD": "BTC-USD",
    "ETHUSDT": "ETH-USD",
    "SOLUSDT": "SOL-USD",
}

# Fallback tickers used when the primary ticker returns no data.
SYMBOL_FALLBACKS: Dict[str, List[str]] = {
    "XAUUSD": ["GC=F", "XAUUSD=X"],
    "BTCUSD": ["BTC-USD"],
    "ETHUSDT": ["ETH-USD"],
    "SOLUSDT": ["SOL-USD"],
}

PIP_SIZE: Dict[str, float] = {
    "XAUUSD": 0.1,
    "EURUSD": 0.0001,
    "GBPUSD": 0.0001,
    "USDJPY": 0.01,
    "GBPJPY": 0.01,
    "EURJPY": 0.01,
    "GBPAUD": 0.0001,
    "NZDUSD": 0.0001,
    "AUDUSD": 0.0001,
    "USDCAD": 0.0001,
    "BTCUSD": 1.0,
    "ETHUSDT": 0.1,
    "SOLUSDT": 0.01,
}

PIP_VALUE_PER_LOT: Dict[str, float] = {
    "XAUUSD": 10.0,
    "EURUSD": 10.0,
    "GBPUSD": 10.0,
    "USDJPY": 9.0,
    "GBPJPY": 9.0,
    "EURJPY": 9.0,
    "GBPAUD": 7.0,
    "NZDUSD": 10.0,
    "AUDUSD": 10.0,
    "USDCAD": 7.5,
    "BTCUSD": 1.0,
    "ETHUSDT": 1.0,
    "SOLUSDT": 1.0,
}

DIGITS: Dict[str, int] = {
    "XAUUSD": 2, "EURUSD": 5, "GBPUSD": 5, "USDJPY": 3, "GBPJPY": 3,
    "EURJPY": 3, "GBPAUD": 5, "NZDUSD": 5, "AUDUSD": 5, "USDCAD": 5,
    "BTCUSD": 2, "ETHUSDT": 2, "SOLUSDT": 3,
}


@dataclass
class Settings:
    # --- Telegram ---
    telegram_enabled: bool = field(default_factory=lambda: _bool("TELEGRAM_ENABLED", True))
    telegram_bot_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    telegram_admin_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_ADMIN_CHAT_ID", ""))

    # --- Dashboard ---
    dashboard_enabled: bool = field(default_factory=lambda: _bool("DASHBOARD_ENABLED", True))
    dashboard_host: str = field(default_factory=lambda: os.getenv("DASHBOARD_HOST", "0.0.0.0"))
    dashboard_port: int = field(default_factory=lambda: _int("DASHBOARD_PORT", 5000))
    dashboard_debug: bool = field(default_factory=lambda: _bool("DASHBOARD_DEBUG", False))
    dashboard_secret_key: str = field(default_factory=lambda: os.getenv("DASHBOARD_SECRET_KEY", "change-me"))

    # --- Logging ---
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())
    log_file: str = str(LOG_DIR / "morgantrader.log")

    # --- Trading universe ---
    symbols: List[str] = field(default_factory=lambda: list(SYMBOL_MAP.keys()))
    symbol_map: Dict[str, str] = field(default_factory=lambda: dict(SYMBOL_MAP))

    # --- Timeframes ---
    tf_primary: str = "M5"
    tf_confirm: str = "M15"
    tf_trend: str = "H1"
    tf_optional: str = "H4"
    use_h4: bool = field(default_factory=lambda: _bool("USE_H4", True))

    # --- Indicators ---
    ema_ribbon: List[int] = field(default_factory=lambda: [5, 11, 15, 18, 21, 24, 28, 34])
    ema_fast: int = 11
    ema_slow: int = 34
    ema_trend: int = 200
    adx_period: int = 14
    adx_threshold: float = field(default_factory=lambda: _float("ADX_THRESHOLD", 25.0))
    atr_period: int = 14
    atr_ma_period: int = 20
    atr_sl_multiplier: float = field(default_factory=lambda: _float("ATR_SL_MULTIPLIER", 2.0))
    risk_reward: float = field(default_factory=lambda: _float("RISK_REWARD", 2.0))
    tp_count: int = 4

    # --- Scanner ---
    scan_interval: int = field(default_factory=lambda: _int("SCAN_INTERVAL", 60))
    cooldown_minutes: int = field(default_factory=lambda: _int("COOLDOWN_MINUTES", 30))
    strict_mode: bool = field(default_factory=lambda: _bool("STRICT_MODE", False))
    min_confidence: int = field(default_factory=lambda: _int("MIN_CONFIDENCE", 65))

    # --- Sessions (UTC hours) ---
    london_session: tuple = (8, 17)
    newyork_session: tuple = (13, 22)
    session_filter_enabled: bool = field(default_factory=lambda: _bool("SESSION_FILTER_ENABLED", True))
    crypto_ignores_session: bool = field(default_factory=lambda: _bool("CRYPTO_IGNORES_SESSION", True))

    # --- Risk ---
    account_balance: float = field(default_factory=lambda: _float("ACCOUNT_BALANCE", 1000.0))
    risk_conservative: float = 1.0
    risk_standard: float = 0.5
    risk_aggressive: float = 0.25

    # --- Confidence scoring weights (max 100) ---
    score_weights: Dict[str, int] = field(default_factory=lambda: {
        "trend": 20,
        "higher_timeframe": 20,
        "adx": 10,
        "atr": 10,
        "bos": 10,
        "choch": 10,
        "order_block": 10,
        "fvg": 10,
        "liquidity_sweep": 10,
    })

    # --- Tiers ---
    tier_conservative: tuple = (85, 100)
    tier_standard: tuple = (75, 84)
    tier_aggressive: tuple = (65, 74)

    crypto_symbols: List[str] = field(default_factory=lambda: ["BTCUSD", "ETHUSDT", "SOLUSDT"])

    def pip_size(self, symbol: str) -> float:
        return PIP_SIZE.get(symbol, 0.0001)

    def pip_value(self, symbol: str) -> float:
        return PIP_VALUE_PER_LOT.get(symbol, 10.0)

    def digits(self, symbol: str) -> int:
        return DIGITS.get(symbol, 5)

    def yahoo_ticker(self, symbol: str) -> str:
        return self.symbol_map.get(symbol, symbol)

    def fallback_tickers(self, symbol: str) -> List[str]:
        return SYMBOL_FALLBACKS.get(symbol, [])

    def risk_for_tier(self, tier: str) -> float:
        return {
            "CONSERVATIVE": self.risk_conservative,
            "STANDARD": self.risk_standard,
            "AGGRESSIVE": self.risk_aggressive,
        }.get(tier.upper(), self.risk_standard)

    def tier_for_score(self, score: float):
        if score >= self.tier_conservative[0]:
            return "CONSERVATIVE"
        if score >= self.tier_standard[0]:
            return "STANDARD"
        if score >= self.tier_aggressive[0]:
            return "AGGRESSIVE"
        return None

    def is_crypto(self, symbol: str) -> bool:
        return symbol in self.crypto_symbols


settings = Settings()
