---
name: telegram-bsc-trending-tokens-digest
description: Build a Telegram bot to post trending-coin digests on BSC, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to post trending-coin digests on BSC and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram BSC Trending Tokens Digest

## Overview
Aggregates trending token data on BSC and sends a periodic digest.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
from datetime import datetime
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
TOP_N = int(os.environ.get("TOP_TRENDING", "10"))
```

## Trending Generator
```python
def fetch_trending():
    pairs = [p for p in requests.get(f"https://api.dexscreener.com/token-pairs/v1/56", timeout=15).json()
             if float(p.get("liquidity", {"usd": 0})["usd"]) > 5000]
    for p in pairs:
        v = float(p.get("volume", {"h24": 0})["h24"])
        pc = float(p.get("priceChange", {"h24": 0})["h24"])
        p["score"] = v * (1 + abs(pc) / 100)
    pairs.sort(key=lambda x: x["score"], reverse=True)
    return pairs[:TOP_N]

def send_digest():
    top = fetch_trending()
    lines = [f"📈 *Trending on BSC — {datetime.now().strftime('%H:%M UTC')}*\n"]
    for i, p in enumerate(top, 1):
        lines.append(f"{i}. *{escape_md(p['baseToken']['symbol'])}* ${float(p['priceUsd']):.8f} Vol: ${float(p['volume']['h24']):,.0f}")
    send_alert(config, "\n".join(lines))
```

## Polling (ScheduledBot)
```python
bot = ScheduledBot(config, interval=3600)  # hourly
@bot.on_poll
def poll():
    send_digest()
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
docker build -t tg-bsc-trending .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e TOP_TRENDING=15 tg-bsc-trending
```

## Production Deployment
| Platform | Notes |
|----------|-------|
| Railway | Set env vars, deploy |
| Fly.io | `fly deploy` with secrets |
| Render | Cron job every hour |

## Risk Filters
- Minimum $5k liquidity threshold
- Exclude pairs with identical buy/sell volume (wash trading)
- Require 20+ unique traders

## Disclaimer
Not financial advice. Rankings can be gamed.
