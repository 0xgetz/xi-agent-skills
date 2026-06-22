---
name: telegram-base-smart-money-tracker
description: Build a Telegram bot to follow profitable wallets on Base, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to follow profitable wallets on Base and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Base Smart Money Tracker

## Overview
Tracks profitable wallets on Base and alerts on new positions.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json, time
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
EXPLORER = "https://basescan.org"
WALLETS = os.environ.get("SMART_WALLETS", "").split(",")
```

## Smart Wallet Monitor
```python
def trades(w, mins=30):
    since = int(time.time()) - mins * 60
    url = f"{EXPLORER}/api?module=account&action=tokentx&address={w}&sort=desc"
    r = requests.get(url, timeout=15).json()
    return [t for t in r.get("result", []) if int(t.get("timeStamp", 0)) >= since]

def poll():
    for w in WALLETS:
        for t in trades(w.strip()):
            typ = "BUY" if t["to"].lower() == w.strip().lower() else "SELL"
            em = "🟢" if typ == "BUY" else "🔴"
            send_alert(config, f"{em} *Smart {typ} on Base*\nWallet: `{w[:6]}...`\nToken: {escape_md(t['tokenSymbol'])}\n[Tx]({EXPLORER}/tx/{t['hash']})")
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
docker build -t tg-base-smart .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e SMART_WALLETS=0xWallet1,0xWallet2 tg-base-smart
```

## Risk Filters
- Track P&L over 30 days before labeling "smart"
- Exclude exchange hot wallets and MEV bots
- Alert on positions > $10k entry value

## Disclaimer
Past performance does not guarantee future results. Not financial advice.
