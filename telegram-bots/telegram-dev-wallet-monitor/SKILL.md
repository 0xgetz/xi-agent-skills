---
name: telegram-dev-wallet-monitor
description: Build a Telegram bot to watch the deployer wallet for sells or transfers, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to watch the deployer wallet for sells or transfers and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Dev Wallet Monitor

## Overview
Monitors deployer wallet addresses for sells and transfers — a rug-pull early warning system.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
WALLETS = os.environ.get("DEPLOYER_WALLETS", "").split(",")
RPC_CHAINS = {"eth":"https://eth.llamarpc.com","bsc":"https://bsc-dataseed.binance.org","arb":"https://arb1.arbitrum.io/rpc"}
```

## Dev Wallet Monitor
```python
def poll():
    for entry in WALLETS:
        parts = entry.strip().split(":")
        addr, chain = parts[0], (parts[1] if len(parts) > 1 else "eth")
        rpc = RPC_CHAINS.get(chain, "https://eth.llamarpc.com")
        logs = requests.post(rpc, json={"jsonrpc":"2.0","method":"eth_getLogs","params":[{"address":addr,"fromBlock":"0x0","toBlock":"latest"}],"id":1}, timeout=10).json().get("result",[])
        for log in logs[:3]:
            send_alert(config, f"🚨 *Dev Activity on {chain.title()}*\nWallet: `{addr[:6]}...{addr[-4:]}`\nTx: [{log['transactionHash'][:10]}...](https://{chain}.etherscan.io/tx/{log['transactionHash']})")
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
docker build -t tg-dev-wallet .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e DEPLOYER_WALLETS=0xDeployer:eth,0xDev2:bsc tg-dev-wallet
```

## Risk Filters
- Flag any sell from deployer to a DEX/router address
- Large transfers (>1% of supply) = critical alert
- Cross-chain deployer activity = elevated suspicion

## Disclaimer
Not financial advice. Dev wallet activity is a strong but not definitive rug signal.
