---
name: telegram-ethereum-airdrop-hunter
description: Build a Telegram bot to surface airdrop opportunities on Ethereum, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to surface airdrop opportunities on Ethereum and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Ethereum Airdrop Hunter

## Overview
Surfaces potential airdrop opportunities on Ethereum by detecting high-activity, low-liquidity tokens.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
```

## Airdrop Detection
```python
def scan():
    pairs = requests.get(f"https://api.dexscreener.com/token-pairs/v1/1", timeout=15).json()
    for p in pairs:
        txs = int(p.get("txns", {"h24": 0})["h24"])
        liq = float(p.get("liquidity", {"usd": 0})["usd"])
        if txs > 500 and liq < 5000:
            msg = (
                f"🎁 *Airdrop Candidate on Ethereum*\n"
                f"Token: {escape_md(p['baseToken']['symbol'])} ({escape_md(p['baseToken']['name'])})\n"
                f"24h TXs: {txs} | Liq: ${liq:,.0f}\n"
                f"→ High TX + low liq = points farming"
            )
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
docker build -t tg-eth-airdrop .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y tg-eth-airdrop
```

## Production Deployment
| Platform | Notes |
|----------|-------|
| Railway | `railway up` with env vars |
| Fly.io | `fly launch`, set secrets |
| Render | Worker service, hourly schedule |

## Risk Filters
- Distinguish real airdrop farming from wash-trading
- Check protocol has official social channels
- Never connect wallet to untrusted dApps shown in alerts
- Flag dusting attacks (free tokens with hidden malicious functions)

## Disclaimer
Not financial advice. Airdrop hunting carries wallet security risks. No reward guaranteed.
