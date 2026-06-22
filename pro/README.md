# 🏛️ XIBot Pro — Institutional Trading System

What separates a 20-year veteran from an amateur isn't more indicators — it's a
**system**: every trade flows through regime detection, scientific position sizing,
portfolio-level risk gates, and disciplined execution, with a full audit trail.

This is that system. **16,000+ lines, verified end-to-end** (`pro/verify_system.py`
runs green, exit 0).

---

## The Pipeline (`orchestrator.py`)

Every decision passes through 8 stages — any stage can veto the trade:

```
1. REGIME      → what market are we in? (trend / range / volatile / risk-off)
2. SIGNAL      → does the strategy fire, given the regime?
3. SENTIMENT   → does crowd positioning confirm or contradict?
4. SIZING      → how much? Kelly × volatility-target × drawdown-scale
5. RISK GATE   → do portfolio limits allow it? (exposure / VaR / daily-loss / corr)
6. EXECUTION   → fill without moving the market (TWAP / VWAP / IS)
7. MONITOR     → stops, trailing, time-stop, VaR breach
8. REPORT      → log everything, audit trail, attribution
```

```python
from pro.orchestrator import TradingSystem, SystemConfig

system = TradingSystem(SystemConfig(capital=25_000, kelly_fraction=0.25))
decision = system.evaluate("BTC", ohlcv_df)
print(decision.explain())
#  ┌─ BTC  →  ENTER_LONG
#  │  Regime: BULL_TRENDING  |  Confidence: 72%
#  │  Size: 2.8% of capital  |  Entry: 109.62  SL: 103.83  TP: 121.21
#  └────────────────────────────────────────
```

---

## Modules

| Module | What it does | Key references |
|--------|--------------|----------------|
| `risk/` | Kelly/Optimal-F/Fixed-Ratio sizing, VaR/CVaR, drawdown control, stop optimization, stress testing, liquidity & correlation limits | Kelly 1956, Vince 1990, Almgren-Chriss 2001 |
| `portfolio/` | Markowitz MPT, Black-Litterman, Hierarchical Risk Parity, performance & drawdown analytics, Brinson attribution, rebalancing | Markowitz 1952, Lopez de Prado 2016 |
| `execution/` | TWAP, VWAP, Implementation Shortfall, Iceberg, Smart Order Router, dark pools, TCA | Almgren-Chriss 2001, Kissell 2006 |
| `regime/` | HMM regimes, trend strength (Hurst, fractal dim, ADX), volatility/correlation/breadth/liquidity regimes, multi-timeframe | Hamilton 1989, Hurst 1951 |
| `volatility/` | GARCH/EGARCH/GJR, 5 realized-vol estimators, HAR-RV, vol surface (SVI), vol targeting | Bollerslev 1986, Corsi 2009, Gatheral 2004 |
| `statarb/` | Cointegration (Engle-Granger, Johansen), pairs trading, Kalman dynamic hedge, PCA baskets | Engle-Granger 1987, Johansen 1991 |
| `sentiment/` | NLP sentiment, Fear & Greed index, social/on-chain aggregation, divergence | — |
| `reporting/` | Interactive HTML reports, trading journal, tamper-proof audit trail, risk & attribution reports | — |
| `orchestrator.py` | **Ties all modules into one decision pipeline** | — |

---

## Install & Verify

```bash
pip install -r pro/requirements.txt          # pinned, conflict-free versions
PYTHONPATH=. python pro/verify_system.py      # must print "ALL SYSTEMS GREEN"
```

The pins matter: `numpy<2.0` + `scipy<1.13` avoid the `np.long` ABI break that
silently corrupts `scipy.sparse`. `statsmodels` and `hmmlearn` are **optional** —
the system degrades gracefully and tells you exactly what to install if a feature
needs them.

---

## Disclaimer

Educational / research use only. **Not financial advice. No profit is guaranteed.**
Markets carry risk of total loss. Position sizing here is scientific, not magic —
it controls risk, it does not eliminate it.


---

## 📡 Paper Trading on LIVE Data (`paper_trader.py`)

Connect the verified orchestrator to **live market data** and trade on paper —
no real money, no exchange keys. This is how a professional validates a system
before risking a cent.

```bash
# one cycle: live data -> orchestrator decision -> realistic fills -> portfolio
PYTHONPATH=. python pro/paper_trader.py --symbols BTC-USD ETH-USD SOL-USD --capital 10000

PYTHONPATH=. python pro/paper_trader.py --status   # show portfolio + live PnL
PYTHONPATH=. python pro/paper_trader.py --reset    # wipe paper state
```

- **Data**: yfinance (full OHLCV for crypto `BTC-USD` and stocks `AAPL`), CoinGecko fallback.
- **Realistic fills**: configurable fee (0.10%) and slippage (0.05%) on every entry/exit.
- **Persistent virtual portfolio**: positions, cash, realized/unrealized PnL saved to `paper_state.json`.
- **Closed-loop risk**: live drawdown / daily-PnL / exposure are fed back into the
  orchestrator's risk gates, so the daily-loss limit and exposure cap actually bind.
- **Stop/target monitoring**: open positions are checked against SL/TP every cycle.

Schedule it (e.g. cron / Railway) to run a cycle every hour and you have a fully
automated paper-trading loop driven by the institutional decision pipeline.
