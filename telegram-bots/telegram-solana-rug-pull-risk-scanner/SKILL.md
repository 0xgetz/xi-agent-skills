---
name: telegram-solana-rug-pull-risk-scanner
description: Build a Telegram bot to score rug-pull risk on Solana, with on-chain/market data sourcing, risk/honeypot filtering, and Telegram alert delivery. Activate when the user wants to score rug-pull risk on Solana and get alerts in Telegram.
icon: send
color: Teal
---

# Telegram Solana Rug Pull Risk Scanner

## Overview
A Telegram bot skill that helps score rug-pull risk on Solana. It is a research/monitoring tool that pushes timely alerts to a Telegram chat or channel — it does **not** guarantee profit and does not place trades for you unless you explicitly wire that in.

## When to use this skill
Activate when the user wants to score rug-pull risk on Solana and receive alerts in Telegram.

## Architecture
1. **Data source** — pull from on-chain RPC/indexers (e.g. Etherscan-style APIs, DEX subgraphs), market-data APIs (CoinGecko/DEXScreener-style), or social feeds.
2. **Detection logic** — apply thresholds/filters (volume, liquidity, holders, contract checks) to find candidates.
3. **Risk filtering** — run safety checks (honeypot, LP lock, holder concentration) before alerting.
4. **Telegram delivery** — send formatted alerts via the Telegram Bot API `sendMessage`.
5. **Scheduling** — run on a poll interval or webhook.

## Telegram delivery pattern
```python
import requests, os
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]   # store as a secret, never hardcode
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
def alert(text):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"})
```

## Safety checklist (critical for alpha hunting)
- Verify the token is **sellable** (honeypot check) before acting.
- Check **liquidity is locked/burned** and not removable by the deployer.
- Inspect **holder concentration** — avoid tokens where a few wallets hold most supply.
- Review the contract for **mint, blacklist, fee-change, and proxy** functions.
- Assume most new tokens fail; size any exposure as money you can fully lose.

## Disclaimer
High-risk and educational. No profit is guaranteed. This is not financial advice. New/low-cap tokens carry extreme risk of total loss, rug pulls, and scams.
