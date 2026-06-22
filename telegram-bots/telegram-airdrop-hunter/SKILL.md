---

name: telegram-airdrop-hunter
description: Build a Telegram bot to surface potential airdrop opportunities and tasks, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to surface potential airdrop opportunities and tasks and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Airdrop Hunter

## Overview
Multi-chain airdrop opportunity scanner that polls DEXScreener for high-activity low-liquidity tokens.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
CHAINS = {"ethereum":1,"arbitrum":42161,"base":8453,"polygon":137,"bsc":56}
```

## Multi-Chain Scan
```python
def scan():
    for name, cid in CHAINS.items():
        pairs = requests.get(f"https://api.dexscreener.com/token-pairs/v1/{cid}", timeout=20).json()
        for p in (pairs if isinstance(pairs, list) else []):
            txs = int(p.get("txns",{}).get("h24",0))
            liq = float(p.get("liquidity",{}).get("usd",0))
            if txs > 500 and liq < 5000:
                msg = f"🎁 *{name.title()} Airdrop*\n{escape_md(p['baseToken']['symbol'])} TXs:{txs} Liq:${liq:,.0f}"
                send_alert(config, msg)
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
docker build -t tg-airdrop-hunter .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y tg-airdrop-hunter
```

## Production
Railway: `railway up` | Fly.io: `fly secrets set BOT_TOKEN=...` | Render: Worker

## Risk Filters
- High TX + low liq = points farming signal
- Dusting attack detection
- Never connect wallet to untrusted dApps

## Disclaimer
High-risk. No reward guaranteed. Not financial advice.
