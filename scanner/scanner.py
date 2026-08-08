"""Multi-pair scanner: scans all pairs concurrently every N seconds."""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

from config.settings import BASE_DIR, settings
from scanner.market_data import MarketData
from scanner.signal_engine import Signal, SignalEngine
from utils.helpers import JsonStore, get_logger, safe_float
from utils.session_time import session_label

log = get_logger("scanner.scanner")

HISTORY = JsonStore(Path(BASE_DIR) / "logs" / "signal_history.json")
STATE = JsonStore(Path(BASE_DIR) / "logs" / "state.json")


class Scanner:
    """Scans every configured pair independently; 30-min cooldown per pair."""

    def __init__(self, on_signal: Optional[Callable[[Signal], None]] = None,
                 on_close: Optional[Callable[[dict, str, float], None]] = None,
                 max_workers: int = 6):
        self.market = MarketData()
        self.engine = SignalEngine()
        self.on_signal = on_signal
        self.on_close = on_close
        self.max_workers = max_workers
        self._cooldowns: Dict[str, datetime] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self.active_signals: List[dict] = []
        self.pair_status: Dict[str, dict] = {
            s: {"symbol": s, "status": "PENDING", "confidence": 0, "price": 0.0,
                "direction": None, "tier": None, "updated": None, "reason": "not scanned yet"}
            for s in settings.symbols
        }
        self.stats = {"scans": 0, "signals": 0, "last_scan": None, "errors": 0}
        self._restore()

    # ------------------------------------------------------------- persistence
    def _restore(self) -> None:
        state = STATE.read({}) or {}
        if isinstance(state, dict):
            self.active_signals = state.get("active_signals", []) or []
            self.stats.update(state.get("stats", {}) or {})

    def _persist(self) -> None:
        STATE.write({"active_signals": self.active_signals, "stats": self.stats})

    # ---------------------------------------------------------------- cooldown
    def in_cooldown(self, symbol: str) -> bool:
        with self._lock:
            until = self._cooldowns.get(symbol)
        return bool(until and datetime.now(timezone.utc) < until)

    def set_cooldown(self, symbol: str) -> None:
        with self._lock:
            self._cooldowns[symbol] = datetime.now(timezone.utc) + timedelta(
                minutes=settings.cooldown_minutes)

    def cooldown_remaining(self, symbol: str) -> int:
        with self._lock:
            until = self._cooldowns.get(symbol)
        if not until:
            return 0
        secs = (until - datetime.now(timezone.utc)).total_seconds()
        return max(0, int(secs // 60))

    # ------------------------------------------------------------- single pair
    def scan_symbol(self, symbol: str) -> Optional[Signal]:
        try:
            snapshot = self.market.load(symbol)
            if not snapshot.ok:
                self._update_status(symbol, "NO DATA", price=snapshot.price, reason="insufficient candles")
                return None
            signal = self.engine.evaluate(snapshot)
            if signal is None:
                self._update_status(symbol, "SCANNING", price=snapshot.price, reason="no valid setup")
                return None
            if self.in_cooldown(symbol):
                self._update_status(symbol, "COOLDOWN", price=snapshot.price,
                                    confidence=signal.confidence,
                                    reason=f"{self.cooldown_remaining(symbol)}m left")
                return None
            self._update_status(symbol, "SIGNAL", price=snapshot.price,
                                confidence=signal.confidence, direction=signal.direction,
                                tier=signal.tier, reason=signal.tier)
            self.set_cooldown(symbol)
            self._register(signal)
            return signal
        except Exception as exc:  # keep the loop alive
            self.stats["errors"] += 1
            log.exception("Error scanning %s: %s", symbol, exc)
            self._update_status(symbol, "ERROR", reason=str(exc)[:120])
            return None

    def _update_status(self, symbol: str, status: str, price: float = 0.0,
                       confidence: int = 0, direction: Optional[str] = None,
                       tier: Optional[str] = None, reason: str = "") -> None:
        self.pair_status[symbol] = {
            "symbol": symbol,
            "status": status,
            "confidence": confidence,
            "price": round(safe_float(price), 5),
            "direction": direction,
            "tier": tier,
            "session": session_label(symbol),
            "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reason": reason,
        }

    def _register(self, signal: Signal) -> None:
        payload = signal.to_dict()
        self.active_signals = [s for s in self.active_signals if s.get("symbol") != signal.symbol][-49:]
        self.active_signals.append(payload)
        self.stats["signals"] += 1
        HISTORY.append(payload)
        self._persist()
        if self.on_signal:
            try:
                self.on_signal(signal)
            except Exception:
                log.exception("on_signal callback failed")

    # ------------------------------------------------------- trade monitoring
    def monitor_open_signals(self) -> None:
        """Check active signals for TP/SL hits using the latest price."""
        still_active = []
        for sig in self.active_signals:
            if sig.get("status") != "ACTIVE":
                continue
            symbol = sig["symbol"]
            price = self.market.feed.get_price(symbol)
            if price is None:
                still_active.append(sig)
                continue
            buy = sig["direction"] == "BUY"
            hit_sl = price <= sig["stop_loss"] if buy else price >= sig["stop_loss"]
            if hit_sl:
                sig["status"] = "SL_HIT"
                if self.on_close:
                    self.on_close(sig, "SL", price)
                HISTORY.append({**sig, "closed_at": datetime.now(timezone.utc).isoformat()})
                continue
            hit_any = False
            for idx, tp in enumerate(sig["take_profits"], start=1):
                reached = price >= tp if buy else price <= tp
                if reached and idx not in sig.get("tp_hit", []):
                    sig.setdefault("tp_hit", []).append(idx)
                    hit_any = True
                    if self.on_close:
                        self.on_close(sig, f"TP{idx}", price)
            if len(sig.get("tp_hit", [])) >= settings.tp_count:
                sig["status"] = "COMPLETED"
                HISTORY.append({**sig, "closed_at": datetime.now(timezone.utc).isoformat()})
                continue
            if hit_any:
                log.info("%s TP progress: %s", symbol, sig["tp_hit"])
            still_active.append(sig)
        self.active_signals = still_active + [s for s in self.active_signals if s.get("status") != "ACTIVE"][-30:]
        self._persist()

    # ------------------------------------------------------------- full sweep
    def scan_once(self) -> List[Signal]:
        started = time.time()
        signals: List[Signal] = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self.scan_symbol, s): s for s in settings.symbols}
            for fut in as_completed(futures):
                result = fut.result()
                if result:
                    signals.append(result)
        self.stats["scans"] += 1
        self.stats["last_scan"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.monitor_open_signals()
        log.info("Scan #%s complete in %.1fs - %s signal(s)",
                 self.stats["scans"], time.time() - started, len(signals))
        return signals

    # ------------------------------------------------------------------- loop
    def run_forever(self) -> None:
        log.info("Scanner started: %s pairs, every %ss", len(settings.symbols), settings.scan_interval)
        while not self._stop.is_set():
            try:
                self.scan_once()
            except Exception:
                log.exception("Scan cycle failed")
            self._stop.wait(settings.scan_interval)

    def start_background(self) -> threading.Thread:
        thread = threading.Thread(target=self.run_forever, name="scanner", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ views
    def snapshot(self) -> dict:
        return {
            "stats": self.stats,
            "pairs": list(self.pair_status.values()),
            "signals": sorted(self.active_signals, key=lambda s: s.get("timestamp", ""), reverse=True),
            "session": session_label(),
            "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "balance": settings.account_balance,
        }
