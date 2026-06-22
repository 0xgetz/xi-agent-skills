---
name: telegram-contract-audit-bot
description: Build a Telegram bot to flag risky functions like mint, blacklist, and proxy upgrades, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to flag risky functions like mint, blacklist, and proxy upgrades and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Contract Audit Bot

## Overview
Analyzes smart contract source code for risky function signatures across multiple chains.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json, re
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
RISK_FUNCS = {"mint":"Unlimited minting","blacklist":"Freeze wallets","pause":"Halt transfers",
    "setTax":"Adjustable tax","upgradeTo":"Upgradeable proxy","transferOwnership":"Ownership transferable"}
```

## Audit Logic
```python
def audit(token, chain="eth"):
    key = os.environ.get(f"{chain.upper()}_ETHERSCAN_KEY", "")
    url = f"https://api.{chain}etherscan.io/api?module=contract&action=getsourcecode&address={token}&apikey={key}"
    r = requests.get(url, timeout=15).json()
    src = r.get("result",[{}])[0].get("SourceCode","") if r.get("status")=="1" else ""
    if not src:
        send_alert(config, f"⚠️ *Audit*\n`{token[:10]}...` Source not verified")
        return
    findings = {s:d for s,d in RISK_FUNCS.items() if re.search(rf"\b{s}\s*\(", src, re.I)}
    em = "🟢" if not findings else "🟡" if len(findings)<=2 else "🔴"
    lines = [f"{em} *Audit Report*\nToken: `{token[:8]}...`\nChain: {chain.title()}"]
    for sig,desc in findings.items():
        lines.append(f"⚠️ `{sig}` — {desc}")
    send_alert(config, "\n".join(lines))
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
docker build -t tg-contract-audit .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e ETH_ETHERSCAN_KEY=key tg-contract-audit
```

## Production
Railway: set all explorer API keys | Fly.io: `fly secrets set ETH_ETHERSCAN_KEY=...`

## Risk Filters
- Unverified source = highest risk
- Proxy + mint = critical (unlimited supply via upgrade)
- Ownable without renounce = elevated risk
- Blacklist function = centralization risk

## Disclaimer
Not a substitute for professional security audit. Not financial advice.
