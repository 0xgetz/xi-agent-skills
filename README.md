# 🤖 XIBot

## 🏛️ Institutional Trading System (`pro/`) — VERIFIED ✅

The `pro/` package is a complete, **end-to-end verified** institutional trading system
(16,000+ lines). Run `PYTHONPATH=. python pro/verify_system.py` → **18/18 checks green**.

- **`pro/orchestrator.py`** — unified 8-stage decision pipeline (regime → signal → sentiment → sizing → risk gate → execution → monitor → report). Any stage can veto a trade.
- **8 modules** — risk, portfolio, execution, regime, volatility, statarb, sentiment, reporting.
- **Robust by design** — optional deps (`statsmodels`, `hmmlearn`) degrade gracefully; numpy/scipy pinned to avoid ABI conflicts; CI re-runs the full verification on every push.

```bash
pip install -r pro/requirements.txt
PYTHONPATH=. python pro/verify_system.py   # → ALL SYSTEMS GREEN
python pro/orchestrator.py                  # demo decision with full reasoning
```

See [`pro/README.md`](pro/README.md) for the full system documentation.

---

