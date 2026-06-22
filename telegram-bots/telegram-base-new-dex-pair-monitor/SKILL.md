---
name: telegram-base-new-dex-pair-monitor
description: Build a Telegram bot to alert on new liquidity pairs on Base, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to alert on new liquidity pairs on Base and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Base New DEX Pair Monitor

## Overview
Monitors factory contracts for newly created trading pairs on Base.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json, time
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
RPC = "https://mainnet.base.org"
FACTORY = "0x5C69bEe701ef814a2B6a3EDD4B1652CB9cc5aA6f"
```

## Pair Detection via Event Logs
```python
def poll_pairs(last):
    topic = "0x0d3648bd0f6ba80134a33ba9275ac585b09b78f4b3b83f0e30b4b0e1a0a2d1e9"
    pl = {"jsonrpc":"2.0","method":"eth_getLogs","params":[{"address":FACTORY,"fromBlock":hex(last),"toBlock":"latest","topics":[topic]}],"id":1}
    return requests.post(RPC, json=pl, timeout=15).json().get("result", [])

last_block = 0
def monitor():
    global last_block
    cur = int(requests.post(RPC, json={"jsonrpc":"2.0","method":"eth_blockNumber","params":[],"id":1}, timeout=10).json()["result"], 16)
    if not last_block:
        last_block = cur
        return
    logs = poll_pairs(last_block)
    for log in logs:
        pair = "0x" + log["topics"][3][26:]
        t0 = "0x" + log["topics"][1][26:]
        t1 = "0x" + log["topics"][2][26:]
        msg = f"🆕 *New DEX Pair on Base*\nPair: `{pair[:10]}...`\nToken0: `{t0[:10]}...`\nToken1: `{t1[:10]}...`"
        send_alert(config, msg)
    last_block = cur
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
docker build -t tg-base-newpairs .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y tg-base-newpairs
```

## Risk Filters
- Flag pairs created by known scam deployer addresses
- Zero initial liquidity = warning
- Unverified source code on token = skip

## Disclaimer
Not financial advice. New pairs are high-risk.
