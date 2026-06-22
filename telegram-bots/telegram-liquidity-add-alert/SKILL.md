---
name: telegram-liquidity-add-alert
description: Build a Telegram bot to alert when liquidity is added to a pool, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to alert when liquidity is added to a pool and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Liquidity Add Alert

## Overview
Alerts when liquidity is added to a DEX pool — can signal new trading opportunities.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
WATCH = os.environ.get("WATCH_PAIRS", "").split(",")
```

## LP Add Detection
```python
def monitor():
    topic = "0x4c209b5fc8ad50758f13e2e1088ba56a560dff690a1c6fef26394f4c03821c4f"
    pl = {"jsonrpc":"2.0","method":"eth_getLogs","params":[{"fromBlock":"0x0","toBlock":"latest","topics":[topic]}],"id":1}
    rpc = os.environ.get("ETH_RPC", "https://eth.llamarpc.com")
    for log in requests.post(rpc, json=pl, timeout=15).json().get("result", []):
        if not WATCH or log["address"] in WATCH:
            send_alert(config, f"💧 *Liquidity Added*\nPair: `{log['address'][:10]}...`\nBlock: {int(log['blockNumber'], 16)}")
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
docker build -t tg-liq-add .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y tg-liq-add
```

## Risk Filters
- Flag if LP added by deployer wallet (vs organic LPs)
- Check if LP token is then locked or burned
- Cross-reference with token honeypot status

## Disclaimer
Not financial advice. LP additions are signals, not guarantees.
