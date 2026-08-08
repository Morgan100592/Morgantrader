"""Technical indicators: EMA ribbon, EMA cross, EMA200, ADX, ATR, SL/TP."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import pandas as pd

from config.settings import settings
from utils.helpers import safe_float


class Indicators:
    # -------------------------------------------------------------- primitives
    @staticmethod
    def ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(period, min_periods=1).mean()

    @staticmethod
    def true_range(df: pd.DataFrame) -> pd.Series:
        prev_close = df["close"].shift(1)
        tr = pd.concat([
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr

    @classmethod
    def atr(cls, df: pd.DataFrame, period: int | None = None) -> pd.Series:
        period = period or settings.atr_period
        return cls.true_range(df).ewm(alpha=1 / period, adjust=False).mean()

    @classmethod
    def adx(cls, df: pd.DataFrame, period: int | None = None) -> pd.DataFrame:
        period = period or settings.adx_period
        up = df["high"].diff()
        down = -df["low"].diff()
        plus_dm = np.where((up > down) & (up > 0), up, 0.0)
        minus_dm = np.where((down > up) & (down > 0), down, 0.0)
        atr = cls.atr(df, period).replace(0, np.nan)
        plus_di = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
        minus_di = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / atr
        dx = ((plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)) * 100
        adx = dx.ewm(alpha=1 / period, adjust=False).mean()
        return pd.DataFrame({
            "plus_di": plus_di.fillna(0),
            "minus_di": minus_di.fillna(0),
            "adx": adx.fillna(0),
        }, index=df.index)

    # ------------------------------------------------------------- ribbon etc
    @classmethod
    def ema_ribbon(cls, df: pd.DataFrame) -> Dict[int, pd.Series]:
        return {p: cls.ema(df["close"], p) for p in settings.ema_ribbon}

    @classmethod
    def ribbon_state(cls, df: pd.DataFrame) -> Dict[str, object]:
        ribbon = cls.ema_ribbon(df)
        values: List[float] = [safe_float(ribbon[p].iloc[-1]) for p in settings.ema_ribbon]
        bullish = all(values[i] > values[i + 1] for i in range(len(values) - 1))
        bearish = all(values[i] < values[i + 1] for i in range(len(values) - 1))
        spread = (max(values) - min(values)) if values else 0.0
        return {
            "values": values,
            "bullish": bullish,
            "bearish": bearish,
            "expanding": spread > 0,
            "spread": spread,
        }

    @classmethod
    def ema_cross(cls, df: pd.DataFrame, lookback: int = 3) -> Dict[str, object]:
        fast = cls.ema(df["close"], settings.ema_fast)
        slow = cls.ema(df["close"], settings.ema_slow)
        diff = fast - slow
        recent = diff.tail(lookback + 1)
        cross_up = bool(len(recent) > 1 and recent.iloc[0] <= 0 and recent.iloc[-1] > 0)
        cross_down = bool(len(recent) > 1 and recent.iloc[0] >= 0 and recent.iloc[-1] < 0)
        return {
            "fast": safe_float(fast.iloc[-1]),
            "slow": safe_float(slow.iloc[-1]),
            "cross_up": cross_up,
            "cross_down": cross_down,
            "above": safe_float(diff.iloc[-1]) > 0,
        }

    @classmethod
    def trend_filter(cls, df: pd.DataFrame) -> Dict[str, object]:
        period = min(settings.ema_trend, max(20, len(df) - 1))
        ema200 = cls.ema(df["close"], period)
        price = safe_float(df["close"].iloc[-1])
        value = safe_float(ema200.iloc[-1])
        slope = value - safe_float(ema200.iloc[-5]) if len(ema200) > 5 else 0.0
        return {
            "ema200": value,
            "period_used": period,
            "price_above": price > value,
            "price_below": price < value,
            "slope": slope,
            "direction": "BUY" if price > value else "SELL",
        }

    @classmethod
    def atr_state(cls, df: pd.DataFrame) -> Dict[str, object]:
        atr = cls.atr(df)
        atr_ma = cls.sma(atr, settings.atr_ma_period)
        current = safe_float(atr.iloc[-1])
        average = safe_float(atr_ma.iloc[-1])
        return {
            "atr": current,
            "atr_ma": average,
            "expanding": current > average,
            "ratio": round(current / average, 3) if average else 0.0,
        }

    @classmethod
    def adx_state(cls, df: pd.DataFrame) -> Dict[str, object]:
        frame = cls.adx(df)
        adx = safe_float(frame["adx"].iloc[-1])
        plus = safe_float(frame["plus_di"].iloc[-1])
        minus = safe_float(frame["minus_di"].iloc[-1])
        return {
            "adx": round(adx, 2),
            "plus_di": round(plus, 2),
            "minus_di": round(minus, 2),
            "strong": adx > settings.adx_threshold,
            "direction": "BUY" if plus > minus else "SELL",
        }

    # ------------------------------------------------------------------ risk
    @classmethod
    def sl_tp(cls, direction: str, entry: float, atr: float) -> Dict[str, object]:
        """2x ATR stop, 4 take profits spaced to a 1:2 final risk-reward."""
        atr = max(safe_float(atr), 1e-9)
        risk = atr * settings.atr_sl_multiplier
        final_reward = risk * settings.risk_reward
        step = final_reward / settings.tp_count
        if direction.upper() == "BUY":
            sl = entry - risk
            tps = [entry + step * i for i in range(1, settings.tp_count + 1)]
        else:
            sl = entry + risk
            tps = [entry - step * i for i in range(1, settings.tp_count + 1)]
        return {
            "stop_loss": sl,
            "take_profits": tps,
            "risk_distance": risk,
            "reward_distance": final_reward,
            "rr": settings.risk_reward,
        }

    # ------------------------------------------------------------------ bundle
    @classmethod
    def analyse(cls, df: pd.DataFrame) -> Dict[str, object]:
        return {
            "price": safe_float(df["close"].iloc[-1]),
            "ribbon": cls.ribbon_state(df),
            "cross": cls.ema_cross(df),
            "trend": cls.trend_filter(df),
            "adx": cls.adx_state(df),
            "atr": cls.atr_state(df),
        }
