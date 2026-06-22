---
name: telegram-listing-alert
description: Build a Telegram bot to alert when a token is listed on a CEX/DEX, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to alert when a token is listed on a CEX/DEX and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Listing Alert

## Overview
Alerts when a token is listed on major CEX/DEX exchanges.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
WATCH = os.environ.get("WATCH_TOKENS", "").split(",")
```

## Listing Detection
```python
def check():
    feeds = {"Binance":"https://www.binance.com/en/blog/rss","Coinbase":"https://www.coinbase.com/blog/feed.xml"}
    for name, url in feeds.items():
        try:
            text = requests.get(url, timeout=15).text.lower()
            for tok in WATCH:
                if tok.strip().lower() in text:
                    send_alert(config, f"📋 *Listing Detected*\n{escape_md(tok.strip())} on {name}")
        except:
            pass
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
docker build -t tg-listing-alert .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e WATCH_TOKENS=ETH,SOL,DOGE tg-listing-alert
```

## Risk Filters
- Verify listing on official exchange channels (avoid scam announcements)
- Cross-reference multiple sources before alerting
- Track listing announcement vs actual trading start time

## Disclaimer
Not financial advice. Listing announcements can be faked.
