---
name: telegram-ethereum-holder-growth-tracker
description: Build a Telegram bot to track holder-count growth on Ethereum, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to track holder-count growth on Ethereum and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Ethereum Holder Growth Tracker

## Overview
Tracks holder count changes for tokens on Ethereum.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
EXPLORER = "https://etherscan.io"
WATCH = os.environ.get("WATCH_TOKENS", "").split(",")
prevs = {}
```

## Holder Tracking
```python
def holders(tok):
    url = f"{EXPLORER}/api?module=token&action=getTokenHolderCount&contractaddress={tok}"
    return int(requests.get(url, timeout=15).json().get("result", 0))

def check():
    for t in WATCH:
        c = holders(t.strip())
        p = prevs.get(t.strip(), c)
        if not p:
            prevs[t.strip()] = c
            continue
        pct = (c - p) / p * 100
        if abs(pct) >= 5:
            em = "📈" if c > p else "📉"
            send_alert(config, f"{em} *Holder Change on Ethereum*\n`{escape_md(t[:10])}...`\n{p} → {c} ({pct:+.1f}%)")
        prevs[t.strip()] = c
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
docker build -t tg-eth-holders .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e WATCH_TOKENS=0xToken1,0xToken2 tg-eth-holders
```

## Risk Filters
- 5% change threshold to avoid noise
- Ignore airdrop claim spikes (surge then dump)
- Check if new holders are unique or sybil clusters

## Disclaimer
Not financial advice. Holder counts can be manipulated via dusting.
