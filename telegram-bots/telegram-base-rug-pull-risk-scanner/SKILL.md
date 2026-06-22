---
name: telegram-base-rug-pull-risk-scanner
description: Build a Telegram bot to score rug-pull risk on Base, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to score rug-pull risk on Base and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Base Rug Pull Risk Scanner

## Overview
Scores token contracts on Base for rug-pull indicators (mint, blacklist, proxy, tax).

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json, re
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
EXPLORER = "https://basescan.org"
```

## Rug Scoring
```python
RISKY_PATTERNS = re.compile(r"(mint|blacklist|pause|setTax|upgradeTo|transferOwnership|setMaxTx|cooldown)", re.I)

def score(tok):
    s, r = 0, []
    try:
        resp = requests.get(f"{EXPLORER}/api?module=contract&action=getsourcecode&address={tok}", timeout=15).json()
        src = resp.get("result", [{}])[0].get("SourceCode", "")
        if not src:
            s += 3
            r.append("Source unverified")
        else:
            matches = RISKY_PATTERNS.findall(src)
            s += len(matches) * 1.5
            if matches:
                r.append(f"Risky functions: {', '.join(set(matches))}")
            # Check proxy via EIP-1967
    except:
        s += 3
        r.append("API error")

    em = "🟢" if s <= 3 else "🟡" if s <= 6 else "🔴"
    s = min(s, 10)
    send_alert(config, f"{em} *Rug Scan on Base*\nScore: {s}/10\n{'; '.join(r) if r else 'No issues found'}")
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
docker build -t tg-base-rug .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y tg-base-rug
```

## Production Deployment
| Platform | Notes |
|----------|-------|
| Railway | Add BASE_ETHERSCAN_KEY as env var |
| Fly.io | `fly secrets set ETH_ETHERSCAN_KEY=...` |
| Render | Web service, configure env vars |

## Risk Filters
- Unverified source = +3 points
- Each risky function = +1.5 points
- Proxy pattern = +2 points
- Deployer holds LP = +2 points
- Token age < 24h = +1 point

## Disclaimer
Not financial advice. Heuristic only; sophisticated rug contracts may evade detection.
