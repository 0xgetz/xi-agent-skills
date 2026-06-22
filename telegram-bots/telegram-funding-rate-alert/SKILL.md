---
name: telegram-funding-rate-alert
description: Build a Telegram bot to alert on extreme perp funding rates, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to alert on extreme perp funding rates and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Funding Rate Alert

## Overview
Alerts on extreme perpetual futures funding rates across exchanges.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
THRESH = float(os.environ.get("FUNDING_THRESHOLD", "0.0005"))
SYMS = os.environ.get("WATCH_SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
```

## Funding Rate Monitor
```python
def check():
    for s in SYMS:
        r = requests.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={s.strip()}", timeout=10).json()
        rate = float(r.get("lastFundingRate", 0))
        if abs(rate) >= THRESH:
            dir = "🔥 Longs paying" if rate > 0 else "❄️ Shorts paying"
            send_alert(config, f"{'💰' if rate > 0 else '🧊'} *Funding Alert*\n{s}\nRate: {rate*100:.4f}%\n{dir}")
```

## Polling (ScheduledBot)
```python
bot = ScheduledBot(config, interval=3600)
@bot.on_poll
def poll():
    check()
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
docker build -t tg-funding-alert .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e WATCH_SYMBOLS=BTCUSDT,ETHUSDT tg-funding-alert
```

## Risk Filters
- Require 2 consecutive readings before alerting
- Cross-reference with open interest for squeeze confirmation

## Disclaimer
Not financial advice. Funding rates can change rapidly.
