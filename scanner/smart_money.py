"""Smart Money Concepts: order blocks, FVG, liquidity sweeps, BOS, CHOCH,
equal highs/lows, premium/discount, supply/demand, support/resistance."""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from utils.helpers import safe_float


class SmartMoney:
    # ------------------------------------------------------------ swing points
    @staticmethod
    def swings(df: pd.DataFrame, left: int = 2, right: int = 2) -> Dict[str, List[dict]]:
        highs, lows = [], []
        h, l = df["high"].values, df["low"].values
        for i in range(left, len(df) - right):
            window_h = h[i - left:i + right + 1]
            window_l = l[i - left:i + right + 1]
            if h[i] == window_h.max() and (window_h.argmax() == left):
                highs.append({"index": i, "price": float(h[i]), "time": str(df.index[i])})
            if l[i] == window_l.min() and (window_l.argmin() == left):
                lows.append({"index": i, "price": float(l[i]), "time": str(df.index[i])})
        return {"highs": highs, "lows": lows}

    # ------------------------------------------------------------ order blocks
    @staticmethod
    def order_blocks(df: pd.DataFrame, lookback: int = 60) -> Dict[str, object]:
        """Last down-candle before an up impulse = bullish OB (and vice versa)."""
        data = df.tail(lookback).reset_index(drop=True)
        bullish: Optional[dict] = None
        bearish: Optional[dict] = None
        for i in range(1, len(data) - 2):
            o, c = data.loc[i, "open"], data.loc[i, "close"]
            nxt1, nxt2 = data.loc[i + 1], data.loc[i + 2]
            body = abs(c - o)
            # bullish OB: bearish candle followed by two strong bullish candles
            if c < o and nxt1["close"] > nxt1["open"] and nxt2["close"] > nxt1["high"]:
                bullish = {
                    "high": float(data.loc[i, "high"]),
                    "low": float(data.loc[i, "low"]),
                    "mid": float((data.loc[i, "high"] + data.loc[i, "low"]) / 2),
                    "strength": float(body),
                    "index": int(i),
                }
            # bearish OB: bullish candle followed by two strong bearish candles
            if c > o and nxt1["close"] < nxt1["open"] and nxt2["close"] < nxt1["low"]:
                bearish = {
                    "high": float(data.loc[i, "high"]),
                    "low": float(data.loc[i, "low"]),
                    "mid": float((data.loc[i, "high"] + data.loc[i, "low"]) / 2),
                    "strength": float(body),
                    "index": int(i),
                }
        price = safe_float(df["close"].iloc[-1])
        return {
            "bullish": bullish,
            "bearish": bearish,
            "bullish_valid": bool(bullish and price >= bullish["low"]),
            "bearish_valid": bool(bearish and price <= bearish["high"]),
        }

    # -------------------------------------------------------- fair value gaps
    @staticmethod
    def fair_value_gaps(df: pd.DataFrame, lookback: int = 60) -> Dict[str, object]:
        data = df.tail(lookback).reset_index(drop=True)
        bull, bear = [], []
        for i in range(2, len(data)):
            h0, l0 = data.loc[i - 2, "high"], data.loc[i - 2, "low"]
            h2, l2 = data.loc[i, "high"], data.loc[i, "low"]
            if l2 > h0:  # bullish gap
                bull.append({"top": float(l2), "bottom": float(h0), "index": int(i)})
            if h2 < l0:  # bearish gap
                bear.append({"top": float(l0), "bottom": float(h2), "index": int(i)})
        price = safe_float(df["close"].iloc[-1])
        last_bull = bull[-1] if bull else None
        last_bear = bear[-1] if bear else None
        return {
            "bullish": last_bull,
            "bearish": last_bear,
            "bullish_count": len(bull),
            "bearish_count": len(bear),
            "bullish_valid": bool(last_bull and price >= last_bull["bottom"]),
            "bearish_valid": bool(last_bear and price <= last_bear["top"]),
        }

    # ------------------------------------------------------- liquidity sweeps
    @classmethod
    def liquidity_sweep(cls, df: pd.DataFrame, lookback: int = 30) -> Dict[str, object]:
        """Wick takes out a prior swing then closes back inside = sweep."""
        data = df.tail(lookback)
        if len(data) < 6:
            return {"lows_swept": False, "highs_swept": False, "level_low": None, "level_high": None}
        prior = data.iloc[:-1]
        last = data.iloc[-1]
        prior_low = float(prior["low"].min())
        prior_high = float(prior["high"].max())
        lows_swept = bool(last["low"] < prior_low and last["close"] > prior_low)
        highs_swept = bool(last["high"] > prior_high and last["close"] < prior_high)
        if not lows_swept:
            recent = data.iloc[-4:]
            lows_swept = bool((recent["low"].min() < prior_low) and (recent["close"].iloc[-1] > prior_low))
        if not highs_swept:
            recent = data.iloc[-4:]
            highs_swept = bool((recent["high"].max() > prior_high) and (recent["close"].iloc[-1] < prior_high))
        return {
            "lows_swept": lows_swept,
            "highs_swept": highs_swept,
            "level_low": prior_low,
            "level_high": prior_high,
        }

    # ------------------------------------------------------------------- BOS
    @classmethod
    def break_of_structure(cls, df: pd.DataFrame, left: int = 2, right: int = 2) -> Dict[str, object]:
        sw = cls.swings(df, left, right)
        close = safe_float(df["close"].iloc[-1])
        last_high = sw["highs"][-1]["price"] if sw["highs"] else None
        last_low = sw["lows"][-1]["price"] if sw["lows"] else None
        bullish = bool(last_high is not None and close > last_high)
        bearish = bool(last_low is not None and close < last_low)
        return {
            "bullish": bullish,
            "bearish": bearish,
            "last_swing_high": last_high,
            "last_swing_low": last_low,
            "direction": "BUY" if bullish else ("SELL" if bearish else None),
        }

    # ----------------------------------------------------------------- CHOCH
    @classmethod
    def change_of_character(cls, df: pd.DataFrame) -> Dict[str, object]:
        """Structure flip: lower-lows sequence broken upward (bullish) or reverse."""
        sw = cls.swings(df)
        highs = [s["price"] for s in sw["highs"]][-3:]
        lows = [s["price"] for s in sw["lows"]][-3:]
        close = safe_float(df["close"].iloc[-1])
        bullish = bearish = False
        if len(highs) >= 2 and len(lows) >= 2:
            downtrend = highs[-1] < highs[-2] and lows[-1] < lows[-2]
            uptrend = highs[-1] > highs[-2] and lows[-1] > lows[-2]
            bullish = bool(downtrend and close > highs[-1])
            bearish = bool(uptrend and close < lows[-1])
        return {
            "bullish": bullish,
            "bearish": bearish,
            "direction": "BUY" if bullish else ("SELL" if bearish else None),
        }

    # ------------------------------------------------------- equal highs/lows
    @classmethod
    def equal_highs_lows(cls, df: pd.DataFrame, tolerance: float = 0.0008) -> Dict[str, object]:
        sw = cls.swings(df)
        def _equal(levels: List[float]) -> bool:
            if len(levels) < 2:
                return False
            a, b = levels[-1], levels[-2]
            ref = max(abs(a), abs(b), 1e-9)
            return abs(a - b) / ref <= tolerance
        highs = [s["price"] for s in sw["highs"]]
        lows = [s["price"] for s in sw["lows"]]
        return {
            "equal_highs": _equal(highs),
            "equal_lows": _equal(lows),
            "high_level": highs[-1] if highs else None,
            "low_level": lows[-1] if lows else None,
        }

    # ------------------------------------------------- premium/discount zones
    @staticmethod
    def premium_discount(df: pd.DataFrame, lookback: int = 100) -> Dict[str, object]:
        data = df.tail(lookback)
        high = float(data["high"].max())
        low = float(data["low"].min())
        price = safe_float(df["close"].iloc[-1])
        rng = max(high - low, 1e-9)
        position = (price - low) / rng
        if position >= 0.7:
            zone = "PREMIUM"
        elif position <= 0.3:
            zone = "DISCOUNT"
        else:
            zone = "EQUILIBRIUM"
        return {
            "zone": zone,
            "position": round(position * 100, 1),
            "range_high": high,
            "range_low": low,
            "equilibrium": low + rng / 2,
            "good_for_buy": position <= 0.5,
            "good_for_sell": position >= 0.5,
        }

    # -------------------------------------------------- supply/demand zones
    @classmethod
    def supply_demand(cls, df: pd.DataFrame, lookback: int = 80) -> Dict[str, object]:
        data = df.tail(lookback)
        atr = float((data["high"] - data["low"]).mean())
        demand, supply = [], []
        arr = data.reset_index(drop=True)
        for i in range(1, len(arr) - 1):
            rng = arr.loc[i, "high"] - arr.loc[i, "low"]
            if rng > atr * 1.5:
                if arr.loc[i, "close"] > arr.loc[i, "open"]:
                    demand.append({"low": float(arr.loc[i, "low"]), "high": float(arr.loc[i, "open"])})
                else:
                    supply.append({"low": float(arr.loc[i, "open"]), "high": float(arr.loc[i, "high"])})
        price = safe_float(df["close"].iloc[-1])
        nearest_demand = min(demand, key=lambda z: abs(price - z["high"])) if demand else None
        nearest_supply = min(supply, key=lambda z: abs(price - z["low"])) if supply else None
        return {
            "demand": nearest_demand,
            "supply": nearest_supply,
            "demand_count": len(demand),
            "supply_count": len(supply),
            "in_demand": bool(nearest_demand and nearest_demand["low"] <= price <= nearest_demand["high"] * 1.001),
            "in_supply": bool(nearest_supply and nearest_supply["low"] * 0.999 <= price <= nearest_supply["high"]),
        }

    # --------------------------------------------- support / resistance + room
    @classmethod
    def support_resistance(cls, df: pd.DataFrame, atr: float, min_room_atr: float = 1.5) -> Dict[str, object]:
        sw = cls.swings(df)
        price = safe_float(df["close"].iloc[-1])
        supports = sorted([s["price"] for s in sw["lows"] if s["price"] < price], reverse=True)
        resistances = sorted([s["price"] for s in sw["highs"] if s["price"] > price])
        support = supports[0] if supports else float(df["low"].tail(50).min())
        resistance = resistances[0] if resistances else float(df["high"].tail(50).max())
        atr = max(safe_float(atr), 1e-9)
        room_up = (resistance - price) / atr
        room_down = (price - support) / atr
        return {
            "support": support,
            "resistance": resistance,
            "support_below": price > support,
            "resistance_above": resistance > price,
            "room_up_atr": round(room_up, 2),
            "room_down_atr": round(room_down, 2),
            "room_for_buy": room_up >= min_room_atr,
            "room_for_sell": room_down >= min_room_atr,
        }

    # ---------------------------------------------------------------- bundle
    @classmethod
    def analyse(cls, df: pd.DataFrame, atr: float) -> Dict[str, object]:
        return {
            "order_blocks": cls.order_blocks(df),
            "fvg": cls.fair_value_gaps(df),
            "sweep": cls.liquidity_sweep(df),
            "bos": cls.break_of_structure(df),
            "choch": cls.change_of_character(df),
            "equal_levels": cls.equal_highs_lows(df),
            "premium_discount": cls.premium_discount(df),
            "supply_demand": cls.supply_demand(df),
            "sr": cls.support_resistance(df, atr),
        }
