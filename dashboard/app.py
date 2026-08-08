"""Flask dashboard: live signals, confidence scores, pair status."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from flask import Flask, jsonify, render_template

try:
    from flask_cors import CORS
except ImportError:  # pragma: no cover
    CORS = None

from config.settings import BASE_DIR, settings
from utils.helpers import JsonStore, get_logger

log = get_logger("dashboard.app")

HISTORY = JsonStore(Path(BASE_DIR) / "logs" / "signal_history.json")
_scanner = None


def set_scanner(scanner) -> None:
    """Attach the running Scanner instance so the dashboard reads live state."""
    global _scanner
    _scanner = scanner


def create_app(scanner=None) -> Flask:
    if scanner is not None:
        set_scanner(scanner)

    app = Flask(__name__, template_folder="templates", static_folder=None)
    app.config["SECRET_KEY"] = settings.dashboard_secret_key
    if CORS is not None:
        CORS(app)

    @app.route("/")
    def index():
        return render_template("dashboard.html",
                               symbols=settings.symbols,
                               interval=settings.scan_interval)

    @app.route("/api/status")
    def api_status():
        if _scanner is None:
            return jsonify({
                "stats": {"scans": 0, "signals": 0, "last_scan": None, "errors": 0},
                "pairs": [], "signals": [], "session": "UNKNOWN",
                "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "balance": settings.account_balance,
                "scanner_running": False,
            })
        data = _scanner.snapshot()
        data["scanner_running"] = True
        return jsonify(data)

    @app.route("/api/signals")
    def api_signals():
        if _scanner is None:
            return jsonify([])
        return jsonify(_scanner.snapshot()["signals"])

    @app.route("/api/history")
    def api_history():
        items = HISTORY.read([]) or []
        return jsonify(items[-100:][::-1])

    @app.route("/api/health")
    def api_health():
        return jsonify({"ok": True, "time": datetime.now(timezone.utc).isoformat()})

    return app


def run_dashboard(scanner=None, host: Optional[str] = None, port: Optional[int] = None,
                  debug: Optional[bool] = None) -> None:
    app = create_app(scanner)
    host = host or settings.dashboard_host
    port = port or settings.dashboard_port
    debug = settings.dashboard_debug if debug is None else debug
    log.info("Dashboard running on http://%s:%s", host, port)
    app.run(host=host, port=port, debug=debug, use_reloader=False, threaded=True)
