---
name: telegram-bsc-volume-spike-alert
description: Build a Telegram bot to alert on volume surges on BSC, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to alert on volume surges on BSC and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram BSC Volume Spike Alert

## Overview
Detects abnormal DEX volume spikes compared to trailing averages on BSC.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json, time
from collections import deque
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
MULT = float(os.environ.get("VOLUME_SPIKE_MULT", "3.0"))
WATCH = os.environ.get("WATCH_TOKENS", "").split(",")
hist = {}
```

## Volume Detection
```python
def vol(tok):
    p = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={tok}", timeout=15).json().get("pairs", [])
    return sum(float(x.get("volume", {"h24": 0})["h24"]) for x in p if x.get("chainId") == "bsc") or 0

def check():
    for t in WATCH:
        v = vol(t.strip())
        if t not in hist:
            hist[t] = deque(maxlen=24)
        hist[t].append((time.time(), v))
        h = [x[1] for x in hist[t]]
        if len(h) < 4:
            continue
        avg = sum(h[:-1]) / (len(h) - 1) or 1
        ratio = h[-1] / avg
        if ratio >= MULT:
            send_alert(config, f"📊 *Volume Spike on BSC*\n`{escape_md(t[:10])}...`\n{ratio:.1f}x baseline\nVol: ${v:,.0f}")
```

## Subgraph Query (DEX Analytics)
```python
# Example: query Uniswap subgraph for pool volume
SUBGRAPH = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3-bsc"
query = {"query": "{ pools(first: 5) { id volumeUSD } }"}
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
docker build -t tg-bsc-vol .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e WATCH_TOKENS=0xToken tg-bsc-vol
```

## Risk Filters
- Minimum 4 data points before triggering
- Exclude pairs with identical buy/sell volume (wash trading)
- Require 20+ unique traders

## Disclaimer
Not financial advice. Volume can be manipulated.
