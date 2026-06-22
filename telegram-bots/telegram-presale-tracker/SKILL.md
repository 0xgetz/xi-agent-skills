---
name: telegram-presale-tracker
description: Build a Telegram bot to track upcoming and live presales, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to track upcoming and live presales and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Presale Tracker

## Overview
Tracks upcoming and live token presales across launchpads.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
from datetime import datetime
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
```

## Presale Discovery
```python
def check():
    presales = requests.get("https://api.pinksale.finance/api/v1/presale/list?chain=56", timeout=15).json().get("data", [])
    now = datetime.now().timestamp()
    for p in presales[:10]:
        s = p.get("startTime", 0)
        if isinstance(s, str):
            s = datetime.fromisoformat(s.replace("Z","+00:00")).timestamp()
        if s <= now + 86400:
            em = "🟢 LIVE" if s <= now else "🟡 UPCOMING"
            send_alert(config, f"{em}\n{escape_md(p.get('name','Unknown'))}\nCap: ${float(p.get('hardCap',0)):,.0f}\n{escape_md(p.get('chain',''))}")
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
docker build -t tg-presale-tracker .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y tg-presale-tracker
```

## Risk Filters
- Verify project team (doxxed vs anonymous)
- Check if smart contract is audited by known firm
- No soft cap = all funds go to team regardless
- No LP lock commitment = high risk

## Disclaimer
Not financial advice. Presales carry extreme risk of scams and rug pulls.
