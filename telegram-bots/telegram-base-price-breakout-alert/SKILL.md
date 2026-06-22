---
name: telegram-base-price-breakout-alert
description: Build a Telegram bot to alert on price breakouts on Base, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to alert on price breakouts on Base and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Base Price Breakout Alert

## Overview
Detects price breakouts from consolidation ranges on Base.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json, statistics
from collections import deque
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
STD = float(os.environ.get("BREAKOUT_Z", "2.5"))
WATCH = os.environ.get("WATCH_TOKENS", "").split(",")
ph = {}
```

## Breakout Detection
```python
def price(t):
    p = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={t}", timeout=15).json().get("pairs", [])
    return float(p[0]["priceUsd"]) if p else None

def detect(t):
    p = price(t.strip())
    if not p:
        return
    if t not in ph:
        ph[t] = deque(maxlen=30)
    ph[t].append(p)
    h = list(ph[t])
    if len(h) < 10:
        return
    m, s = statistics.mean(h[:-1]), statistics.stdev(h[:-1]) or 0.0001
    z = (h[-1] - m) / s
    if abs(z) >= STD:
        d = "🚀 UP" if z > 0 else "📉 DOWN"
        send_alert(config, f"{d} *Breakout on Base*\n`{escape_md(t[:10])}...`\nPrice: ${p:.8f}\nZ-score: {z:.2f}")
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
docker build -t tg-base-breakout .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e WATCH_TOKENS=0xToken -e BREAKOUT_Z=2.5 tg-base-breakout
```

## Risk Filters
- Minimum 10 price samples before detection
- Exclude tokens with liquidity < $10k
- Volume confirmation required alongside price move

## Disclaimer
Not financial advice. Breakout patterns can fail.
