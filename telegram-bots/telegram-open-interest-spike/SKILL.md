---
name: telegram-open-interest-spike
description: Build a Telegram bot to alert on large open-interest changes, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to alert on large open-interest changes and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Open Interest Spike

## Overview
Alerts on large open interest changes in perpetual futures markets.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
PCT = float(os.environ.get("OI_CHANGE_PCT", "15"))
SYMS = os.environ.get("WATCH_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
prev = {}
```

## OI Monitor
```python
def check():
    for s in SYMS:
        c = float(requests.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={s.strip()}", timeout=10).json().get("openInterest", 0))
        p = prev.get(s.strip(), c)
        if not p:
            prev[s.strip()] = c
            continue
        d = (c - p) / p * 100
        if abs(d) >= PCT:
            send_alert(config, f"{'🔥' if d>0 else '💥'} *OI {'Surge' if d>0 else 'Crash'}*\n{s}\n{d:+.1f}%\nCurrent: ${c:,.0f}")
        prev[s.strip()] = c
```

## Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install lib-gumloop-telegram requests
COPY bot.py .
CMD ["python", "bot.py"]
```
```bash
docker build -t tg-oi-alert .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e OI_CHANGE_PCT=15 -e WATCH_SYMBOLS=BTCUSDT,ETHUSDT tg-oi-alert
```

## Risk Filters
- Require 2 consecutive readings before alert
- Cross-reference OI change with price movement

## Disclaimer
Not financial advice. Binance data only.
