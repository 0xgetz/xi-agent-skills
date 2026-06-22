---
name: telegram-arbitrum-insider-buy-alert
description: Build a Telegram bot to flag insider/team buys on Arbitrum, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to flag insider/team buys on Arbitrum and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Arbitrum Insider Buy Alert

## Overview
Flags wallets on Arbitrum that buy tokens before public announcements.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
EXPLORER = "https://arbiscan.io"
```

## Insider Detection
```python
def early_buyers(tok, block):
    url = f"{EXPLORER}/api?module=account&action=tokentx&contractaddress={tok}&startblock={block}&endblock={block+100}&sort=asc"
    buyers = {}
    for tx in requests.get(url, timeout=15).json().get("result", []):
        addr = tx["to"].lower()
        val = float(tx.get("value", 0)) / 10**int(tx.get("tokenDecimal", 18))
        buyers[addr] = buyers.get(addr, 0) + val
    return buyers
```

## Webhook Mode
```python
from flask import Flask, request
app = Flask(__name__)
@app.route("/webhook/insider-check", methods=["POST"])
def check():
    data = request.json
    buyers = early_buyers(data["token"], data.get("deployBlock", 0))
    for addr, amt in sorted(buyers.items(), key=lambda x: -x[1])[:5]:
        send_alert(config, f"👀 *Insider Buy*\nToken: {data['token'][:8]}...\nWallet: `{addr[:6]}...`\nAmount: {amt:,.2f}")
    return "ok", 200
```

## Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install lib-gumloop-telegram requests flask
COPY bot.py .
CMD ["python", "bot.py"]
```
```bash
docker build -t tg-arb-insider .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y tg-arb-insider
```

## Risk Filters
- Flag wallets appearing in 3+ token launches as early buyer
- Check if buyer was funded by CEX before purchase
- Multi-wallet buys from same funder = coordinated insider

## Disclaimer
Not financial advice. Insider detection is probabilistic.
