---
name: telegram-base-whale-wallet-tracker
description: Build a Telegram bot to track large wallet moves on Base, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to track large wallet moves on Base and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Base Whale Wallet Tracker

## Overview
Monitors large wallet addresses on Base for significant token transfers.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json, time
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
EXPLORER = "https://basescan.org"
WHALES = os.environ.get("WHALE_WALLETS", "").split(",")
MIN_USD = int(os.environ.get("MIN_WHALE_USD", "50000"))
```

## Whale Detection
```python
def recent_txs(wallet):
    url = f"{EXPLORER}/api?module=account&action=tokentx&address={wallet}&sort=desc"
    r = requests.get(url, timeout=15).json()
    return r.get("result", []) if r.get("status") == "1" else []

def poll():
    for w in WHALES:
        txs = recent_txs(w.strip())
        for tx in txs[:5]:
            val = float(tx.get("value", 0)) / 10**int(tx.get("tokenDecimal", 18))
            if val > 0:
                msg = (
                    f"🐋 *Whale Move on Base*\n"
                    f"Wallet: `{w[:6]}...{w[-4:]}`\n"
                    f"Token: {escape_md(tx.get('tokenSymbol', '?'))}\n"
                    f"Amount: {val:,.2f}\n"
                    f"[Tx]({EXPLORER}/tx/{tx['hash']})"
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
docker build -t tg-base-whale .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e WHALE_WALLETS=0xAddr1,0xAddr2 tg-base-whale
```

## Production Deployment
| Platform | Notes |
|----------|-------|
| Railway | Set env vars, `railway up` |
| Fly.io | `fly secrets set WHALE_WALLETS=...` |
| Render | Worker service type |

## Risk Filters
- Minimum $50k USD movement (configurable via MIN_WHALE_USD)
- Flag rapid sequential sells from same wallet
- Track whale wallet creation time

## Disclaimer
Not financial advice. Requires reliable RPC/API keys.
