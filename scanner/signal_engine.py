"""Signal engine: entry conditions, AI confidence score (0-100), tiers, risk."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config.settings import settings
from scanner.indicators import Indicators
from scanner.market_data import MarketSnapshot
from scanner.smart_money import SmartMoney
from utils.helpers import calc_lot_size, get_logger, round_price, pips_between
from utils.session_time import is_session_active, session_label

log = get_logger("scanner.signal_engine")


@dataclass
class Signal:
    symbol: str
    direction: str
    tier: str
    confidence: int
    entry: float
    stop_loss: float
    take_profits: List[float]
    atr: float
    adx: float
    session: str
    timestamp: str
    score_breakdown: Dict[str, int] = field(default_factory=dict)
    conditions: Dict[str, bool] = field(default_factory=dict)
    risk: Dict[str, float] = field(default_factory=dict)
    notes: str = ""
    status: str = "ACTIVE"
    tp_hit: List[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def sl_pips(self) -> float:
        return pips_between(self.symbol, self.entry, self.stop_loss)


class SignalEngine:
    """Turns a multi-timeframe snapshot into a scored Signal (or None)."""

    def __init__(self, strict: Optional[bool] = None):
        self.strict = settings.strict_mode if strict is None else strict

    # ------------------------------------------------------------- scoring
    def score(self, direction: str, primary: dict, confirm: dict, trend: dict,
              h4: Optional[dict], smc: dict) -> Dict[str, int]:
        w = settings.score_weights
        buy = direction == "BUY"
        out: Dict[str, int] = {k: 0 for k in w}

        # Trend (EMA200 + ribbon on primary)
        trend_ok = (primary["trend"]["price_above"] if buy else primary["trend"]["price_below"])
        ribbon_ok = (primary["ribbon"]["bullish"] if buy else primary["ribbon"]["bearish"])
        out["trend"] = w["trend"] if (trend_ok and ribbon_ok) else (w["trend"] // 2 if trend_ok else 0)

        # Higher timeframe agreement (M15 + H1 (+H4))
        htf_votes = [
            confirm["trend"]["price_above"] if buy else confirm["trend"]["price_below"],
            trend["trend"]["price_above"] if buy else trend["trend"]["price_below"],
        ]
        if h4:
            htf_votes.append(h4["trend"]["price_above"] if buy else h4["trend"]["price_below"])
        agree = sum(1 for v in htf_votes if v)
        out["higher_timeframe"] = int(round(w["higher_timeframe"] * agree / len(htf_votes)))

        # ADX
        adx = primary["adx"]
        if adx["strong"] and adx["direction"] == direction:
            out["adx"] = w["adx"]
        elif adx["strong"]:
            out["adx"] = w["adx"] // 2

        # ATR expansion
        out["atr"] = w["atr"] if primary["atr"]["expanding"] else 0

        # Smart money
        out["bos"] = w["bos"] if (smc["bos"]["bullish"] if buy else smc["bos"]["bearish"]) else 0
        out["choch"] = w["choch"] if (smc["choch"]["bullish"] if buy else smc["choch"]["bearish"]) else 0
        out["order_block"] = w["order_block"] if (
            smc["order_blocks"]["bullish_valid"] if buy else smc["order_blocks"]["bearish_valid"]) else 0
        out["fvg"] = w["fvg"] if (
            smc["fvg"]["bullish_valid"] if buy else smc["fvg"]["bearish_valid"]) else 0
        out["liquidity_sweep"] = w["liquidity_sweep"] if (
            smc["sweep"]["lows_swept"] if buy else smc["sweep"]["highs_swept"]) else 0

        total = min(100, sum(out.values()))
        out["TOTAL"] = total
        return out

    # ---------------------------------------------------------- conditions
    def conditions(self, direction: str, symbol: str, primary: dict, confirm: dict,
                   trend: dict, smc: dict) -> Dict[str, bool]:
        buy = direction == "BUY"
        cross = primary["cross"]
        return {
            "ema_cross": cross["cross_up"] if buy else cross["cross_down"],
            "ema_alignment": cross["above"] if buy else (not cross["above"]),
            "price_vs_ema200": primary["trend"]["price_above"] if buy else primary["trend"]["price_below"],
            "ribbon": primary["ribbon"]["bullish"] if buy else primary["ribbon"]["bearish"],
            "adx_strong": primary["adx"]["strong"],
            "atr_expanding": primary["atr"]["expanding"],
            "bos": smc["bos"]["bullish"] if buy else smc["bos"]["bearish"],
            "choch": smc["choch"]["bullish"] if buy else smc["choch"]["bearish"],
            "liquidity_sweep": smc["sweep"]["lows_swept"] if buy else smc["sweep"]["highs_swept"],
            "order_block": smc["order_blocks"]["bullish_valid"] if buy else smc["order_blocks"]["bearish_valid"],
            "fvg": smc["fvg"]["bullish_valid"] if buy else smc["fvg"]["bearish_valid"],
            "structure_level": smc["sr"]["support_below"] if buy else smc["sr"]["resistance_above"],
            "room_to_target": smc["sr"]["room_for_buy"] if buy else smc["sr"]["room_for_sell"],
            "zone_ok": smc["premium_discount"]["good_for_buy"] if buy else smc["premium_discount"]["good_for_sell"],
            "htf_agree": (confirm["trend"]["price_above"] and trend["trend"]["price_above"]) if buy
                         else (confirm["trend"]["price_below"] and trend["trend"]["price_below"]),
            "session_active": is_session_active(symbol),
        }

    # -------------------------------------------------------------- evaluate
    def evaluate(self, snapshot: MarketSnapshot) -> Optional[Signal]:
        if not snapshot.ok:
            return None
        symbol = snapshot.symbol
        p_df = snapshot.frame(settings.tf_primary)
        c_df = snapshot.frame(settings.tf_confirm)
        t_df = snapshot.frame(settings.tf_trend)
        h4_df = snapshot.frame(settings.tf_optional)

        primary = Indicators.analyse(p_df)
        confirm = Indicators.analyse(c_df)
        trend = Indicators.analyse(t_df)
        h4 = Indicators.analyse(h4_df) if len(h4_df) >= 60 else None

        atr = primary["atr"]["atr"]
        smc = SmartMoney.analyse(p_df, atr)

        best: Optional[Signal] = None
        for direction in ("BUY", "SELL"):
            conds = self.conditions(direction, symbol, primary, confirm, trend, smc)
            if not conds["session_active"]:
                continue
            # Core non-negotiables
            core = conds["ema_alignment"] and conds["price_vs_ema200"] and conds["structure_level"]
            if not core:
                continue
            if self.strict and not all(conds.values()):
                continue
            breakdown = self.score(direction, primary, confirm, trend, h4, smc)
            total = breakdown["TOTAL"]
            tier = settings.tier_for_score(total)
            if tier is None or total < settings.min_confidence:
                continue

            entry = round_price(symbol, primary["price"])
            levels = Indicators.sl_tp(direction, entry, atr)
            sl = round_price(symbol, levels["stop_loss"])
            tps = [round_price(symbol, tp) for tp in levels["take_profits"]]
            risk = calc_lot_size(symbol, entry, sl, tier)

            signal = Signal(
                symbol=symbol,
                direction=direction,
                tier=tier,
                confidence=int(total),
                entry=entry,
                stop_loss=sl,
                take_profits=tps,
                atr=round(atr, 6),
                adx=primary["adx"]["adx"],
                session=session_label(symbol),
                timestamp=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                score_breakdown={k: v for k, v in breakdown.items() if k != "TOTAL"},
                conditions=conds,
                risk=risk,
                notes=self._notes(tier, smc),
            )
            if best is None or signal.confidence > best.confidence:
                best = signal
        return best

    @staticmethod
    def _notes(tier: str, smc: dict) -> str:
        zone = smc["premium_discount"]["zone"]
        base = {
            "CONSERVATIVE": "High-confidence setup. Suitable for swing trades with full position size.",
            "STANDARD": "Standard setup. Day-trade sizing (0.5% risk). Manage actively.",
            "AGGRESSIVE": "AGGRESSIVE - High Risk. Scalp only, 0.25% risk, experienced traders.",
        }[tier]
        return f"{base} Price in {zone} zone."
