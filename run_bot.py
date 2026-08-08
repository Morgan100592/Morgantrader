#!/usr/bin/env python3
"""Morgantrader launcher.

Usage:
    python run_bot.py                  # scanner + telegram + dashboard
    python run_bot.py --test-telegram   # verify Telegram credentials
    python run_bot.py --dashboard       # dashboard only (no scanning)
    python run_bot.py --scan-once       # one scan sweep then exit
    python run_bot.py --no-dashboard    # scanner only
    python run_bot.py --report daily     # send a report and exit
"""
from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from datetime import datetime, timezone

from config.settings import settings
from dashboard.app import run_dashboard, set_scanner
from scanner.scanner import Scanner
from telegram.bot import notifier
from utils.helpers import get_logger, setup_logging
from utils.session_time import local_time_str, session_label

log = get_logger("run_bot")

BANNER = r"""
  __  __                              _                 _
 |  \/  | ___  _ __ __ _  __ _ _ __ | |_ _ __ __ _  __| | ___ _ __
 | |\/| |/ _ \| '__/ _` |/ _` | '_ \| __| '__/ _` |/ _` |/ _ \ '__|
 | |  | | (_) | | | (_| | (_| | | | | |_| | | (_| | (_| |  __/ |
 |_|  |_|\___/|_|  \__, |\__,_|_| |_|\__|_|  \__,_|\__,_|\___|_|
                   |___/     Multi-Pair SMC Signal Bot
"""

_reports_sent = {"daily": None, "weekly": None, "monthly": None}


def build_scanner() -> Scanner:
    def on_signal(sig):
        log.info("SIGNAL %s %s %s (%s)", sig.symbol, sig.direction, sig.confidence, sig.tier)
        if notifier.enabled:
            notifier.send_signal(sig)

    def on_close(sig_dict, event, price):
        log.info("%s %s at %s", sig_dict.get("symbol"), event, price)
        if notifier.enabled:
            notifier.on_trade_event(sig_dict, event, price)

    return Scanner(on_signal=on_signal, on_close=on_close)


def report_scheduler() -> None:
    """Sends daily (21:00 UTC), weekly (Fri 21:00) and monthly (1st 21:05) reports."""
    while True:
        try:
            now = datetime.now(timezone.utc)
            key = now.strftime("%Y-%m-%d")
            if now.hour == 21 and _reports_sent["daily"] != key:
                notifier.send_daily_report()
                _reports_sent["daily"] = key
                if now.weekday() == 4:
                    notifier.send_weekly_report()
                    _reports_sent["weekly"] = key
                if now.day == 1:
                    notifier.send_monthly_report()
                    _reports_sent["monthly"] = key
        except Exception:
            log.exception("Report scheduler error")
        time.sleep(300)


def main() -> int:
    parser = argparse.ArgumentParser(description="Morgantrader trading bot")
    parser.add_argument("--test-telegram", action="store_true", help="Send a test Telegram message and exit")
    parser.add_argument("--dashboard", action="store_true", help="Run only the web dashboard")
    parser.add_argument("--scan-once", action="store_true", help="Run a single scan sweep and exit")
    parser.add_argument("--no-dashboard", action="store_true", help="Run the scanner without the dashboard")
    parser.add_argument("--no-telegram", action="store_true", help="Disable Telegram alerts for this run")
    parser.add_argument("--report", choices=["daily", "weekly", "monthly"], help="Send a report and exit")
    parser.add_argument("--port", type=int, help="Override dashboard port")
    args = parser.parse_args()

    setup_logging()
    print(BANNER)
    log.info("Local time: %s | Session: %s", local_time_str(), session_label())

    if args.no_telegram:
        notifier.enabled = False

    if args.test_telegram:
        ok = notifier.test_connection()
        print("Telegram test:", "SUCCESS - check your chat" if ok else "FAILED - see logs above")
        return 0 if ok else 1

    if args.report:
        method = {"daily": notifier.send_daily_report,
                  "weekly": notifier.send_weekly_report,
                  "monthly": notifier.send_monthly_report}[args.report]
        return 0 if method() else 1

    if args.dashboard:
        run_dashboard(None, port=args.port)
        return 0

    scanner = build_scanner()
    set_scanner(scanner)

    if args.scan_once:
        signals = scanner.scan_once()
        print(f"\nScan complete: {len(signals)} signal(s)")
        for sig in signals:
            print(f"  {sig.symbol:8s} {sig.direction:4s} {sig.tier:12s} {sig.confidence}/100 "
                  f"entry={sig.entry} sl={sig.stop_loss} tps={sig.take_profits}")
        for pair in scanner.snapshot()["pairs"]:
            print(f"  - {pair['symbol']:8s} {pair['status']:9s} {pair['reason']}")
        return 0

    if notifier.enabled and notifier.configured:
        notifier.send_startup()
    elif notifier.enabled:
        log.warning("Telegram enabled but token/chat id missing - alerts will be skipped.")

    scanner.start_background()
    threading.Thread(target=report_scheduler, name="reports", daemon=True).start()

    def shutdown(signum, _frame):
        log.info("Shutting down (signal %s)…", signum)
        scanner.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    if settings.dashboard_enabled and not args.no_dashboard:
        run_dashboard(scanner, port=args.port)
    else:
        while True:
            time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
