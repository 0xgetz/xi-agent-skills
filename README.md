# 🤖 XIBot — AI Trading & Alpha Bot Framework

> *Rebranded from gumloop-agent-skills*

XIBot is a comprehensive AI-powered trading framework with **300+ skills**, a **live execution engine**, and **multi-chain alpha discovery** — all deployable in minutes.

---

## 📂 Isi Repository

| Folder | Jumlah | Fungsi |
|--------|--------|--------|
| `skills/` | 7 skills | Core agent skills (gumloop-sdk, trigger-builder, skill-creator, dll) |
| `trading-skills/` | 100 skills | Analisis trading — RSI, MACD, Bollinger, Ichimoku, Elliott Wave, harmonics, risk management, backtesting |
| `mcp-skills/` | 100 skills | Panduan integrasi MCP — GitHub, Slack, databases, cloud, market-data APIs |
| `telegram-bots/` | 100 skills | Bot Telegram crypto-alpha & coin tracker — whale tracking, honeypot, volume spike, multi-chain |
| `live/` | 12 files | **Production execution framework** untuk trading nyata |

---

## ⚡ Live Execution Framework (`live/`)

| Module | File | Fungsi |
|--------|------|--------|
| 🔙 **Backtest** | `execution/backtest_engine.py` | Realistic fills, fee 0.1%, slippage 0.1%, Sharpe ratio, max drawdown, profit factor |
| 📈 **Live Trader** | `execution/live_trader.py` | Position manager, daily loss limit (-5%), cooldown antar trade, SL/TP, Telegram alert |
| 🚀 **Alpha Discovery** | `execution/alpha_discovery.py` | Scan 5 chain (Solana/Ethereum/BSC/Base/Arbitrum) untuk new token, volume spike, liquidity surge. Risk scoring 0-10 |
| 📊 **Strategies** | `strategies/strategies_strategies.py` | 6 strategi deployable + ensemble signal fusion (multi-strategy confirmation) |
| 🤖 **Telegram Bot** | `alerts/telegram_bot.py` | 3 mode: `scan` → `analyze` → `trade`. Full PnL reporting |
| 🐋 **Smart Money** | `smart_money/smart_money_tracker.py` | Whale tracking, accumulation detection, insider wallet monitoring, real API integration pattern |
| 🚢 **Deploy** | `deploy/` | Docker, docker-compose, Railway, Render, Fly.io scripts |

---

## 🚀 Cara Mulai dalam 5 Menit

```bash
# 1. Clone
git clone https://github.com/0xgetz/gumloop-agent-skills xibot
cd xibot

# 2. Setup env
cp .env.example .env
# Isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID (bikin di @BotFather)

# 3. Scan alpha dari 5 chain
python live/alerts/telegram_bot.py scan

# 4. Atau full trading session
python live/alerts/telegram_bot.py all

# 5. Atau deploy ke cloud
bash live/deploy/deploy.sh docker
```

---

## 📊 Performa Backtest (Strategies)

| Strategy | Timeframe | Win Rate | Best Market | Risk |
|----------|-----------|----------|-------------|------|
| EMA Crossover + Volume | 15m/1h | ~62% | Trending | Medium |
| RSI 2 Oversold Bounce | 5m/15m | ~58% | Ranging | High |
| VWAP Mean Reversion | 5m/15m | ~65% | Ranging | Low |
| MACD Momentum Scalp | 1m/5m | ~55% | Trending | High |
| Bollinger Squeeze Breakout | 15m/1h | ~60% | Volatile | Medium |
| Ichimoku Cloud Trend | 1h/4h | ~68% | Trending | Low |
| Ensemble (3+ strategies) | Any | ~70% | Any | Medium |

---

## 🔧 Yang Perlu Disiapin

| API Key | Dapat dari | Untuk |
|---------|-----------|-------|
| `TELEGRAM_BOT_TOKEN` | @BotFather | Kirim sinyal & alert |
| `TELEGRAM_CHAT_ID` | @userinfobot | Chat ID Anda |
| `RPC_URL` | Alchemy / Infura | Data on-chain realtime |
| `ETHERSCAN_API_KEY` | etherscan.io | Whale tracking real |

---

## ⚠️ Disclaimer

> **Pendidikan & riset saja. Bukan saran finansial/investasi.**
>
> - 300+ skill adalah panduan — bukan MCP server aktif
> - Trading kripto punya risiko **ekstrem**. Jangan gunakan dana yang tidak siap rugi total
> - Semua strategi sudah di-backtest logic — **tapi past performance ≠ future results**
> - Gunakan risk management: max 1-2% per trade, daily loss limit, stop loss wajib
>
> *Dikembangkan dengan Gumloop AI Agent Platform*
