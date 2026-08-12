# Morgantrader Pro

Multi-pair Smart Money Concepts signal bot. **Free data only** (Yahoo Finance — no API key,
no OANDA, works from Nigeria). Sends Telegram alerts and serves a live web dashboard.

> Signals only. The bot does **not** place trades on a broker.

## Features

- 13 pairs scanned **simultaneously** every 60s: XAUUSD, EURUSD, GBPUSD, USDJPY, GBPJPY,
  EURJPY, GBPAUD, NZDUSD, AUDUSD, USDCAD, BTCUSD, ETHUSDT, SOLUSDT
- Timeframes: M5 primary, M15 confirmation, H1 trend, H4 optional (resampled)
- EMA ribbon (5,11,15,18,21,24,28,34), EMA11/EMA34 cross, EMA200 filter, ADX(14) > 25,
  ATR(14) vs its moving average
- Smart Money: order blocks, fair value gaps, liquidity sweeps, BOS, CHOCH, equal highs/lows,
  premium/discount, supply/demand, support/resistance with room check
- AI confidence score 0–100 (trend 20, HTF 20, ADX 10, ATR 10, BOS 10, CHOCH 10, OB 10, FVG 10, sweep 10)
- Tiers: **CONSERVATIVE 85–100** (1% risk, swing) · **STANDARD 75–84** (0.5%, day) ·
  **AGGRESSIVE 65–74** (0.25%, scalp, high risk)
- Risk: 2× ATR stop, 4 TPs spaced to a final 1:2 R:R, auto lot sizing
- Session filter: London 08:00–17:00 UTC, New York 13:00–22:00 UTC (crypto runs 24/7)
- 30-minute cooldown **per pair** only — different pairs can fire at the same time
- Telegram: signal alerts per tier, TP-hit, SL-hit, daily/weekly/monthly reports
- Flask dashboard auto-refreshing every 5 seconds

## Install

```bash
git clone <your-repo> && cd MorgantraderPro
pip install -r requirements.txt
cp .env.example .env      # then edit .env
```

Edit `.env`:

```
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=8872764045:AAHWsotqblhlxyxTJ6NblhpkfvsWJYFHW2Q
TELEGRAM_CHAT_ID=8176888003
TELEGRAM_ADMIN_CHAT_ID=8176888003
DASHBOARD_PORT=$PORT
ACCOUNT_BALANCE=1000
```

Get your chat id: message your bot, then open
`https://api.telegram.org/bot<TOKEN>/getUpdates` and read `chat.id`.

## Run

```bash
python run_bot.py                 # scanner + telegram + dashboard (default)
python run_bot.py --test-telegram # verify Telegram setup
python run_bot.py --scan-once     # one sweep of all 13 pairs, prints results
python run_bot.py --dashboard     # dashboard only
python run_bot.py --no-dashboard  # scanner only (low memory VPS)
python run_bot.py --report daily  # send daily report now
```

Dashboard: `http://localhost:5000` (or `http://<server-ip>:5000`).

## View it from your Android phone

**Option A — Termux (runs entirely on the phone, easiest):**
1. Install **Termux** from F-Droid (the Play Store build is outdated).
2. In Termux:
   ```bash
   pkg update && pkg install python git -y
   pip install --upgrade pip wheel
   pip install -r requirements.txt
   python run_bot.py
   ```
   If `pandas`/`numpy` are slow to build, run `pkg install python-numpy python-pandas` first.
3. Open Chrome on the phone and go to `http://127.0.0.1:5000`.
4. Keep it alive: `termux-wake-lock`, and run with `nohup python run_bot.py &`.

**Option B — PythonAnywhere free tier (always on, view from any browser):**
1. Sign up, open a Bash console, `git clone` this folder (or upload the ZIP and unzip).
2. `pip install --user -r requirements.txt`
3. Web tab → Add a new web app → **Flask** → Python 3.10, then set the WSGI file to:
   ```python
   import sys
   path = '/home/<yourusername>/MorgantraderPro'
   if path not in sys.path: sys.path.insert(0, path)
   from dashboard.app import create_app
   application = create_app()
   ```
4. Tasks tab → add a scheduled task running `python3 /home/<you>/MorgantraderPro/run_bot.py --scan-once --no-dashboard`
   (free tier allows one daily task; for continuous scanning use an Always-On task on a paid plan,
   or keep a Bash console running `python3 run_bot.py --no-dashboard`).
5. Visit `https://<yourusername>.pythonanywhere.com` from your phone browser.
   Note: free PythonAnywhere blocks non-whitelisted outbound hosts — `finance.yahoo.com`
   and `api.telegram.org` need to be reachable; if Yahoo is blocked, use Option A or a VPS.

**Option C — VPS (recommended for 24/7):**
```bash
sudo apt update && sudo apt install python3-pip -y
pip3 install -r requirements.txt
nohup python3 run_bot.py > logs/run.out 2>&1 &
```
Then open `http://<vps-ip>:5000` on your phone (open port 5000 in the firewall).

**Simplest of all:** you don't need the dashboard at all — Telegram alerts land straight in
your phone's Telegram app. Run with `--no-dashboard` and just watch the chat.

## Tuning

Environment variables you can add to `.env`:
`ADX_THRESHOLD`, `ATR_SL_MULTIPLIER`, `RISK_REWARD`, `SCAN_INTERVAL`, `COOLDOWN_MINUTES`,
`MIN_CONFIDENCE`, `STRICT_MODE` (require every entry condition), `SESSION_FILTER_ENABLED`,
`CRYPTO_IGNORES_SESSION`, `USE_H4`, `ACCOUNT_BALANCE`.

`STRICT_MODE=false` (default) uses the confidence score as the gate with core structure checks
enforced; `STRICT_MODE=true` requires **all** entry conditions from the spec to be true at once
(very few signals per week).

## Layout

```
config/      settings + .env
scanner/     yahoo_data, market_data, indicators, smart_money, signal_engine, scanner
telegram/    bot.py (Telegram HTTP API notifier)
dashboard/   Flask app + dashboard.html
utils/       helpers, session_time
logs/        morgantrader.log, signal_history.json, state.json
run_bot.py   launcher
```

## Security

Rotate any bot token that has been shared in plain text: Telegram `@BotFather` → `/revoke`,
then put the new token in `.env`. Never commit `.env`.

## Disclaimer

Educational software. Trading carries substantial risk of loss. Not financial advice.
