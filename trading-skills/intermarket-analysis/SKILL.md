---
name: intermarket-analysis
description: Analyze markets using Intermarket Analysis (cross-asset). Read relationships between stocks, bonds, commodities, and FX. Activate when the user asks to analyze, interpret, or build signals based on Intermarket Analysis or cross-asset.
icon: chart-candlestick
color: Green
---

# Intermarket Analysis

## Overview
Intermarket Analysis (cross-asset) — Read relationships between stocks, bonds, commodities, and FX.

## When to use this skill
Use when the user asks to:
- Analyze or interpret Intermarket Analysis on a chart or dataset
- Build buy/sell signals or alerts based on cross-asset
- Combine Intermarket Analysis with other indicators for confirmation

## How it works
Read relationships between stocks, bonds, commodities, and FX. Apply it on OHLCV data (open, high, low, close, volume) for any timeframe. Always confirm with price structure, trend context, and at least one independent indicator before acting.

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
