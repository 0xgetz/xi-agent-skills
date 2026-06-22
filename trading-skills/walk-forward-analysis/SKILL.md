---
name: walk-forward-analysis
description: Analyze markets using Walk Forward Analysis (out-of-sample test). Validate strategies with rolling in/out-of-sample windows. Activate when the user asks to analyze, interpret, or build signals based on Walk Forward Analysis or out-of-sample test.
icon: chart-candlestick
color: Green
---

# Walk Forward Analysis

## Overview
Walk Forward Analysis (out-of-sample test) — Validate strategies with rolling in/out-of-sample windows.

## When to use this skill
Use when the user asks to:
- Analyze or interpret Walk Forward Analysis on a chart or dataset
- Build buy/sell signals or alerts based on out-of-sample test
- Combine Walk Forward Analysis with other indicators for confirmation

## How it works
Validate strategies with rolling in/out-of-sample windows. Apply it on OHLCV data (open, high, low, close, volume) for any timeframe. Always confirm with price structure, trend context, and at least one independent indicator before acting.

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
