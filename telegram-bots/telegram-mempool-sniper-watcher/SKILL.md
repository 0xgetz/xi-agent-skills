---
name: telegram-mempool-sniper-watcher
description: Build a Telegram bot to watch pending transactions for early entries, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to watch pending transactions for early entries and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Mempool Sniper Watcher

## Overview
Watches the mempool for pending transactions targeting specific contracts — surfacing early entries and sniper activity.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
RPC = os.environ.get("ETH_RPC", "https://eth.llamarpc.com")
WATCH = os.environ.get("WATCH_CONTRACTS", "").split(",")
```

## Mempool Monitor
```python
def poll():
    p = requests.post(RPC, json={"jsonrpc":"2.0","method":"txpool_content","params":[],"id":1}, timeout=15).json().get("result",{}).get("pending",{})
    for nonce, txs in p.items():
        items = txs.items() if isinstance(txs, dict) else enumerate(txs)
        for h, tx in items:
            to = tx.get("to", "").lower()
            for w in WATCH:
                if w.strip().lower() in to:
                    val = int(tx.get("value", "0x0"), 16) / 1e18
                    gas = int(tx.get("gasPrice", "0x0"), 16) / 1e9
                    send_alert(config, f"🎯 *Mempool TX*\nTarget: `{w[:10]}...`\nValue: {val:.4f} ETH\nGas: {gas:.1f} Gwei\nFrom: `{tx.get('from','')[:8]}...`")
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
docker build -t tg-mempool-watcher .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e ETH_RPC=https://eth.llamarpc.com -e WATCH_CONTRACTS=0xContract tg-mempool-watcher
```

## Risk Filters
- Gas > 50 Gwei = automated sniper flag
- Ignore failed/reverted transactions
- Flag rapid sequential buys from same wallet

## Disclaimer
Not financial advice. Mempool data is ephemeral.
