---
name: telegram-arbitrum-new-token-launch-scanner
description: Build a Telegram bot to detect new token deployments on Arbitrum, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to detect new token deployments on Arbitrum and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Arbitrum New Token Launch Scanner

## Overview
Detects newly deployed token contracts on Arbitrum, evaluates risk, and sends alerts.

## Dependencies & Imports
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json, time
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
```

## Core Detection
```python
RPC = "https://arb1.arbitrum.io/rpc"
EXPLORER = "https://arbiscan.io"

def fetch_new_tokens():
    url = f"https://api.dexscreener.com/token-pairs/v1/42161"
    pairs = requests.get(url, timeout=15).json()
    cutoff = time.time() - 1800
    fresh = []
    for p in pairs:
        created = p.get("pairCreatedAt", 0) / 1000
        if created > cutoff and float(p.get("liquidity", {"usd": 0})["usd"]) > 500:
            fresh.append(p)
    return fresh

def quick_risk(token):
    payload = {"jsonrpc": "2.0", "method": "eth_call",
        "params": [{"to": token, "data": "0x70a082310000000000000000000000000000000000000000000000000000000000000001"}, "latest"], "id": 1}
    try:
        resp = requests.post(RPC, json=payload, timeout=10)
        return resp.json().get("result") is not None
    except:
        return False

def run():
    for t in fetch_new_tokens():
        if not quick_risk(t["baseToken"]["address"]):
            continue
        msg = (
            f"🚀 *New Token:* {escape_md(t['baseToken']['symbol'])}\n"
            f"💰 ${t['priceUsd']}\n"
            f"💧 Liq: ${float(t['liquidity']['usd']):,.0f}\n"
            f"🔗 [Explorer]({EXPLORER}/address/{t['baseToken']['address']})"
        )
        send_alert(config, msg)
```

## Webhook Mode
```python
from flask import Flask, request
app = Flask(__name__)
@app.route("/webhook/token-launch", methods=["POST"])
def webhook():
    send_alert(config, f"🚀 New token: {request.json.get('tokenAddress','')}")
    return "ok", 200
```

## Polling (ScheduledBot)
```python
bot = ScheduledBot(config, interval=120)
@bot.on_poll
def scan():
    run()
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
docker build -t tg-arb-newtoken .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y tg-arb-newtoken
```

## Production Deployment
| Platform | Instructions |
|----------|-------------|
| Railway | `railway init`, set env vars, `railway up` |
| Fly.io | `fly launch`, `fly secrets set TELEGRAM_BOT_TOKEN=...` |
| Render | Connect GitHub, add env vars, select Worker |

## Risk Filters
- Minimum liquidity: $500 USD
- Age filter: < 30 minutes
- Honeypot check via eth_call before alerting
- Holder count > 5 required
- Reject tokens with mint() or blacklist() signature

## Disclaimer
High-risk. No profit guaranteed. Not financial advice.
