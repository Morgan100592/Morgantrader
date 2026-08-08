"""Telegram notifier.

Uses the Telegram Bot HTTP API directly through `requests` so that this local
package named `telegram` never clashes with the `python-telegram-bot` import.
"""
from __future__ import annotations

import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

from config.settings import BASE_DIR, settings
from utils.helpers import JsonStore, fmt_price, get_logger, safe_float
from utils.session_time import local_time_str

log = get_logger("telegram.bot")

API = "https://api.telegram.org/bot{token}/{method}"
HISTORY = JsonStore(Path(BASE_DIR) / "logs" / "signal_history.json")

TIER_EMOJI = {"CONSERVATIVE": "🟢🏆", "STANDARD": "🟡", "AGGRESSIVE": "🔴⚡"}
TIER_HEADER = {
    "CONSERVATIVE": "CONSERVATIVE - HIGH CONFIDENCE",
    "STANDARD": "STANDARD - TRADE WITH CAUTION",
    "AGGRESSIVE": "AGGRESSIVE - HIGH RISK (SCALP)",
}
TIER_WARNING = {
    "CONSERVATIVE": "Full position size. Recommended for swing trades.",
    "STANDARD": "⚠️ Caution: reduce size to 0.5% risk. Day-trade only.",
    "AGGRESSIVE": "🚨 HIGH RISK: 0.25% risk max. Experienced traders only.",
}
SCORE_LABELS = {
    "trend": "Trend (20)",
    "higher_timeframe": "Higher TF (20)",
    "adx": "ADX (10)",
    "atr": "ATR (10)",
    "bos": "BOS (10)",
    "choch": "CHOCH (10)",
    "order_block": "Order Block (10)",
    "fvg": "Fair Value Gap (10)",
    "liquidity_sweep": "Liquidity Sweep (10)",
}


class TelegramNotifier:
    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None,
                 admin_chat_id: Optional[str] = None, enabled: Optional[bool] = None):
        self.token = token or settings.telegram_bot_token
        self.chat_id = chat_id or settings.telegram_chat_id
        self.admin_chat_id = admin_chat_id or settings.telegram_admin_chat_id
        self.enabled = settings.telegram_enabled if enabled is None else enabled
        self._lock = threading.Lock()
        self._session = requests.Session()

    # ------------------------------------------------------------------ core
    @property
    def configured(self) -> bool:
        return bool(self.enabled and self.token and self.chat_id)

    def _post(self, method: str, payload: dict) -> Optional[dict]:
        if not self.token:
            log.warning("Telegram token missing; message not sent.")
            return None
        url = API.format(token=self.token, method=method)
        try:
            with self._lock:
                resp = self._session.post(url, json=payload, timeout=20)
            data = resp.json() if resp.content else {}
            if not resp.ok or not data.get("ok", False):
                log.error("Telegram %s failed [%s]: %s", method, resp.status_code, data or resp.text)
                return None
            return data
        except requests.RequestException as exc:
            log.error("Telegram request error: %s", exc)
            return None

    def send(self, text: str, chat_id: Optional[str] = None) -> bool:
        if not self.enabled:
            log.info("Telegram disabled; skipping message.")
            return False
        target = chat_id or self.chat_id
        if not target:
            log.warning("No Telegram chat id configured.")
            return False
        result = self._post("sendMessage", {
            "chat_id": target,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        })
        return result is not None

    def send_admin(self, text: str) -> bool:
        return self.send(text, chat_id=self.admin_chat_id or self.chat_id)

    def test_connection(self) -> bool:
        info = self._post("getMe", {})
        if not info:
            log.error("Telegram getMe failed - check TELEGRAM_BOT_TOKEN.")
            return False
        username = info.get("result", {}).get("username", "unknown")
        log.info("Connected to Telegram bot @%s", username)
        ok = self.send(
            "✅ <b>Morgantrader connected</b>\n"
            f"Bot: @{username}\n"
            f"Pairs monitored: {len(settings.symbols)}\n"
            f"Scan interval: {settings.scan_interval}s\n"
            f"Time: {local_time_str()}"
        )
        return ok

    # --------------------------------------------------------------- signals
    def format_signal(self, sig: dict) -> str:
        symbol = sig["symbol"]
        emoji = TIER_EMOJI.get(sig["tier"], "📊")
        arrow = "🟩 BUY" if sig["direction"] == "BUY" else "🟥 SELL"
        tps = "\n".join(
            f"   TP{i}: <code>{fmt_price(symbol, tp)}</code>"
            for i, tp in enumerate(sig["take_profits"], start=1)
        )
        breakdown = "\n".join(
            f"   {'✅' if v > 0 else '➖'} {SCORE_LABELS.get(k, k)}: {v}"
            for k, v in sig.get("score_breakdown", {}).items()
        )
        risk = sig.get("risk", {})
        return (
            f"{emoji} <b>{TIER_HEADER.get(sig['tier'], sig['tier'])}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>{symbol}</b>  {arrow}\n"
            f"Confidence: <b>{sig['confidence']}/100</b>\n\n"
            f"📍 Entry: <code>{fmt_price(symbol, sig['entry'])}</code>\n"
            f"🛑 Stop Loss: <code>{fmt_price(symbol, sig['stop_loss'])}</code>"
            f" ({risk.get('sl_pips', 0)} pips)\n"
            f"🎯 Take Profits (1:2 RR):\n{tps}\n\n"
            f"💰 Lots: <b>{risk.get('lots', 0)}</b> | Risk: {risk.get('risk_percent', 0)}%"
            f" (${risk.get('risk_amount', 0)}) of ${risk.get('balance', 0)}\n"
            f"📈 ADX: {sig.get('adx')} | ATR: {sig.get('atr')}\n\n"
            f"<b>Confidence breakdown</b>\n{breakdown}\n\n"
            f"🕒 Session: {sig.get('session')}\n"
            f"⏰ {sig.get('timestamp')} UTC\n"
            f"ℹ️ {sig.get('notes','')}\n"
            f"{TIER_WARNING.get(sig['tier'], '')}"
        )

    def send_signal(self, signal) -> bool:
        sig = signal if isinstance(signal, dict) else signal.to_dict()
        return self.send(self.format_signal(sig))

    def send_tp_hit(self, sig: dict, level: str, price: float) -> bool:
        symbol = sig["symbol"]
        return self.send(
            f"🎉 <b>{level} HIT</b> - {symbol} {sig['direction']}\n"
            f"Price: <code>{fmt_price(symbol, price)}</code>\n"
            f"Entry: <code>{fmt_price(symbol, sig['entry'])}</code>\n"
            f"Tier: {sig['tier']} | Confidence: {sig['confidence']}/100\n"
            f"⏰ {local_time_str()}\n"
            f"👉 Consider moving SL to protect profit."
        )

    def send_sl_hit(self, sig: dict, price: float) -> bool:
        symbol = sig["symbol"]
        return self.send(
            f"🛑 <b>STOP LOSS HIT</b> - {symbol} {sig['direction']}\n"
            f"Price: <code>{fmt_price(symbol, price)}</code>\n"
            f"Entry: <code>{fmt_price(symbol, sig['entry'])}</code>\n"
            f"Risked: {sig.get('risk', {}).get('risk_percent', 0)}%\n"
            f"⏰ {local_time_str()}\n"
            f"Stay disciplined - the edge plays out over many trades."
        )

    def on_trade_event(self, sig: dict, event: str, price: float) -> bool:
        if event.upper() == "SL":
            return self.send_sl_hit(sig, price)
        return self.send_tp_hit(sig, event.upper(), price)

    # --------------------------------------------------------------- reports
    @staticmethod
    def _history_since(hours: int) -> List[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        items = HISTORY.read([]) or []
        out = []
        for item in items:
            ts = item.get("timestamp")
            if not ts:
                continue
            try:
                when = datetime.fromisoformat(str(ts))
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if when >= cutoff:
                out.append(item)
        return out

    def build_report(self, title: str, hours: int) -> str:
        items = self._history_since(hours)
        seen = {}
        for item in items:
            seen[f"{item.get('symbol')}|{item.get('timestamp')}"] = item
        rows = list(seen.values())
        tiers = Counter(r.get("tier") for r in rows)
        dirs = Counter(r.get("direction") for r in rows)
        pairs = Counter(r.get("symbol") for r in rows)
        tp_hits = sum(len(r.get("tp_hit", []) or []) for r in rows)
        sl_hits = sum(1 for r in rows if r.get("status") == "SL_HIT")
        avg_conf = round(sum(safe_float(r.get("confidence")) for r in rows) / len(rows), 1) if rows else 0
        top = "\n".join(f"   {p}: {c}" for p, c in pairs.most_common(5)) or "   none"
        return (
            f"📊 <b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Signals: <b>{len(rows)}</b>\n"
            f"Conservative: {tiers.get('CONSERVATIVE', 0)} | "
            f"Standard: {tiers.get('STANDARD', 0)} | "
            f"Aggressive: {tiers.get('AGGRESSIVE', 0)}\n"
            f"Buy: {dirs.get('BUY', 0)} | Sell: {dirs.get('SELL', 0)}\n"
            f"TP levels hit: {tp_hits} | SL hits: {sl_hits}\n"
            f"Average confidence: {avg_conf}/100\n\n"
            f"<b>Most active pairs</b>\n{top}\n\n"
            f"⏰ {local_time_str()}"
        )

    def send_daily_report(self) -> bool:
        return self.send(self.build_report("DAILY REPORT (24h)", 24))

    def send_weekly_report(self) -> bool:
        return self.send(self.build_report("WEEKLY REPORT (7d)", 24 * 7))

    def send_monthly_report(self) -> bool:
        return self.send(self.build_report("MONTHLY REPORT (30d)", 24 * 30))

    def send_startup(self) -> bool:
        return self.send(
            "🚀 <b>Morgantrader is live</b>\n"
            f"Pairs: {', '.join(settings.symbols)}\n"
            f"Timeframes: {settings.tf_primary}/{settings.tf_confirm}/{settings.tf_trend}"
            f"{'/' + settings.tf_optional if settings.use_h4 else ''}\n"
            f"Data: Yahoo Finance (free)\n"
            f"Tiers: 85+ Conservative | 75-84 Standard | 65-74 Aggressive\n"
            f"⏰ {local_time_str()}"
        )

    def send_error(self, message: str) -> bool:
        return self.send_admin(f"⚠️ <b>Morgantrader error</b>\n<code>{message[:900]}</code>")


notifier = TelegramNotifier()
