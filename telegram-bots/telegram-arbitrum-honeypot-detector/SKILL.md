---
name: telegram-arbitrum-honeypot-detector
description: Build a Telegram bot to verify sellability before buying on Arbitrum, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to verify sellability before buying on Arbitrum and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Arbitrum Honeypot Detector

## Overview
Checks token sellability on Arbitrum via eth_call simulation.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
RPC = "https://arb1.arbitrum.io/rpc"
```

## Detection Logic
```python
def simulate_xfer(token, fr, to, amt):
    data = "0xa9059cbb" + to[2:].zfill(64) + amt[2:].zfill(64)
    pl = {"jsonrpc":"2.0","method":"eth_call","params":[{"from":fr,"to":token,"data":data},"latest"],"id":1}
    r = requests.post(RPC, json=pl, timeout=10).json()
    return r.get("result") not in (None, "0x")

def check(token):
    b, s, a = "0x0000000000000000000000000000000000000001", "0x0000000000000000000000000000000000000002", hex(10**18)
    buy = simulate_xfer(token, b, s, a)
    sell = simulate_xfer(token, s, b, a)
    if buy and not sell:
        send_alert(config, f"🐝 *HONEYPOT*\nBuy: ✅ Sell: ❌")
    else:
        send_alert(config, f"✅ *Safe*\nBuy: {'✅' if buy else '❌'} Sell: {'✅' if sell else '❌'}")
```

## Additional Checks
- Query sellFee if ABI known (fee-on-transfer detection)
- Check proxy via EIP-1967 storage slot
- Compare balanceOf before/after simulated transfer

## Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install lib-gumloop-telegram requests flask
COPY bot.py .
CMD ["python", "bot.py"]
```
```bash
docker build -t tg-arb-honeypot .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y tg-arb-honeypot
```

## Risk Filters
- Revert-on-sell = instant honeypot flag
- Fee > 10% = high risk
- Proxy contract = additional scrutiny
- Unverified source code = elevated risk

## Disclaimer
Not financial advice. Simulation not foolproof.
