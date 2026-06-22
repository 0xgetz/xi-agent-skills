---
name: telegram-bsc-liquidity-removal-alert
description: Build a Telegram bot to warn on liquidity pulls on BSC, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to warn on liquidity pulls on BSC and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram BSC Liquidity Removal Alert

## Overview
Monitors DEX pools on BSC for LP removal events — a classic rug-pull precursor.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
RPC = "https://bsc-dataseed.binance.org"
WATCH = os.environ.get("WATCH_PAIRS", "").split(",")
```

## LP Monitoring
```python
def lp_bal(pair):
    pl = {"jsonrpc":"2.0","method":"eth_call","params":[{"to":pair,"data":"0x70a082310000000000000000000000000000000000000000000000000000000000000001"},"latest"],"id":1}
    return int(requests.post(RPC, json=pl, timeout=10).json().get("result","0x0"), 16)

prev = {}
def monitor():
    for pair in WATCH:
        cur = lp_bal(pair.strip())
        p = prev.get(pair.strip(), cur)
        if p and cur < p:
            pct = (p - cur) / p * 100
            msg = (
                f"⚠️ *Liquidity Removed on BSC*\n"
                f"Pair: `{pair[:10]}...`\n"
                f"Removed: {pct:.1f}%\n"
                f"LP remaining: {cur / 10**18:.2f}"
            )
            send_alert(config, msg)
        prev[pair.strip()] = cur
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
docker build -t tg-bsc-liq-removal .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e WATCH_PAIRS=0xPair1,0xPair2 tg-bsc-liq-removal
```

## Risk Filters
- >5% LP removed = alert
- First 24h removal = critical
- Check if deployer wallet initiated the removal

## Disclaimer
Not financial advice. LP removal is an early warning, not a guarantee.
