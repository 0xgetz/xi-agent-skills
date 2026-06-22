---
name: anchored-vwap
description: Analyze markets using Anchored VWAP (anchored volume price). Anchor VWAP to a key event to track fair value from that point. Activate when the user asks to analyze, interpret, or build signals based on Anchored VWAP or anchored volume price.
icon: chart-candlestick
color: Green
---

# Anchored VWAP

## Overview
Anchored VWAP (anchored volume price) — Anchor VWAP to a key event to track fair value from that point.

## When to use this skill
Use when the user asks to:
- Analyze or interpret Anchored VWAP on a chart or dataset
- Build buy/sell signals or alerts based on anchored volume price
- Combine Anchored VWAP with other indicators for confirmation

## How it works
Anchor VWAP to a key event to track fair value from that point. Apply it on OHLCV data (open, high, low, close, volume) for any timeframe. Always confirm with price structure, trend context, and at least one independent indicator before acting.

## Reading the signals
- Bullish bias: signal aligns with higher highs/higher lows and rising volume.
- Bearish bias: signal aligns with lower highs/lower lows and rising volume.
- No-trade: conflicting context or low volatility/volume.

## Worked example (Python)
```python
import pandas as pd
# df has columns: open, high, low, close, volume (datetime index)
# Compute the indicator, then generate signals
# (use pandas/numpy or ta libraries; validate on out-of-sample data)
```

## Risk management
- Define stop-loss from structure or ATR before entry.
- Size positions by fixed-fractional risk (e.g. 0.5–1% per trade).
- Never rely on a single indicator; require confluence.

## Common pitfalls
- Over-optimizing parameters to past data (curve fitting).
- Ignoring the higher-timeframe trend.
- Acting on signals during low liquidity.

> Educational analysis only. Not financial advice.
