---
name: telegram-social-sentiment-tracker
description: Build a Telegram bot to summarize social buzz and sentiment per token, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to summarize social buzz and sentiment per token and get alerts in Telegram.
icon: send
color: Teal
---
# Telegram Social Sentiment Tracker

## Overview
Aggregates social buzz and sentiment analysis for specified tokens.

## Dependencies
```python
from lib.gumloop_telegram import BotConfig, send_alert, build_alert, ScheduledBot, escape_md
import requests, os, json
```

## Bot Config
```python
config = BotConfig(bot_token=os.environ["TELEGRAM_BOT_TOKEN"], chat_id=os.environ["TELEGRAM_CHAT_ID"])
WATCH = os.environ.get("WATCH_TOKENS", "bitcoin,ethereum").split(",")
POS = {"moon","pump","bullish","gem","lfg","hodl","rocket"}
NEG = {"dump","bearish","sell","scam","rug","fud","rekt"}
```

## Sentiment Scoring
```python
def score(text):
    w = set(text.lower().split())
    p, n = len(w & POS), len(w & NEG)
    return (p - n) / (p + n) if p + n else 0

def digest():
    lines = ["📊 *Social Sentiment*\n"]
    for t in WATCH:
        # In production: fetch from Twitter/Reddit API
        score_val = 0  # placeholder
        em = "🟢" if score_val > 0.2 else "🔴" if score_val < -0.2 else "🟡"
        lines.append(f"{em} {escape_md(t.title())}: sentiment score {score_val:.2f}")
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
docker build -t tg-sentiment .
docker run -d -e TELEGRAM_BOT_TOKEN=x -e TELEGRAM_CHAT_ID=y -e WATCH_TOKENS="bitcoin,ethereum,solana" tg-sentiment
```

## Risk Filters
- Filter bot accounts from sentiment calculation
- Detect coordinated shilling (same message across accounts)
- Cross-reference sentiment with on-chain activity

## Disclaimer
Heuristic only. Sentiment can be gamed. Not financial advice.
