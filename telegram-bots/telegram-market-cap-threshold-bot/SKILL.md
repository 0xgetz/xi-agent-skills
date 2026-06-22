---
name: telegram-market-cap-threshold-bot
description: Build a Telegram bot to alert when a token crosses a market-cap level, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to alert when a token crosses a market-cap level and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Market Cap Threshold Bot

## Overview
Alerts when a token crosses a specified market cap threshold.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
WATCH = os.environ.get("WATCH_TOKENS", "bitcoin:1000000000000").split(",")
```

## Market Cap Monitor
```python
def mcap(sym):
    return requests.get(f"https://api.coingecko.com/api/v3/coins/{sym.lower()}", timeout=15).json().get("market_data",{}).get("market_cap",{}).get("usd", 0)

def check():
    for entry in WATCH:
        parts = entry.strip().split(":")
        sym, th = parts[0], float(parts[1]) if len(parts) > 1 else 1_000_000_000
        c = mcap(sym)
        if c >= th:
            send_alert(config, f"🎯 *MCAP Threshold*\n{escape_md(sym.upper())}\n${c:,.0f} > ${th:,.0f}")
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
docker build -t tg-mcap-bot .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e WATCH_TOKENS="bitcoin:1000000000000,ethereum:500000000000" tg-mcap-bot
```

## Risk Filters
- Cross-reference with CoinMarketCap to verify
- Flag tokens with suspicious circulating supply changes

## Disclaimer
Not financial advice. Data may be delayed.
