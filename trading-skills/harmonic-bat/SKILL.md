---
name: harmonic-bat
description: Analyze markets using Harmonic Bat (bat pattern). Trade the bat harmonic with precise Fibonacci ratios. Activate when the user asks to analyze, interpret, or build signals based on Harmonic Bat or bat pattern.
icon: chart-candlestick
color: Green
---

# Harmonic Bat

## Overview
Harmonic Bat (bat pattern) — Trade the bat harmonic with precise Fibonacci ratios.

## When to use this skill
Use when the user asks to:
- Analyze or interpret Harmonic Bat on a chart or dataset
- Build buy/sell signals or alerts based on bat pattern
- Combine Harmonic Bat with other indicators for confirmation

## How it works
Trade the bat harmonic with precise Fibonacci ratios. Apply it on OHLCV data (open, high, low, close, volume) for any timeframe. Always confirm with price structure, trend context, and at least one independent indicator before acting.

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
