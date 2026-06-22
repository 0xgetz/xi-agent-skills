import pandas as pd, numpy as np
from typing import Dict, List, Tuple, Callable
from dataclasses import dataclass

# ── Strategy Registry ──────────────────────────────────────

@dataclass
class StrategyMeta:
    name: str
    description: str
    timeframe: str  # 1m, 5m, 15m, 1h, 4h, 1d
    expected_win_rate: float
    avg_holding_period: str
    best_market: str  # trending, ranging, volatile
    risk_level: str  # low, medium, high

STRATEGIES: Dict[str, Tuple[Callable, StrategyMeta]] = {}

def register(name, meta):
    def decorator(func):
        STRATEGIES[name] = (func, meta)
        return func
    return decorator

# ── Strategy 1: EMA Crossover with Volume Confirmation ─────

@register("ema_crossover", StrategyMeta(
    name="EMA Crossover + Volume",
    description="9 EMA crosses above/below 21 EMA with volume spike confirmation",
    timeframe="15m/1h",
    expected_win_rate=0.62,
    avg_holding_period="2-6 hours",
    best_market="trending",
    risk_level="medium",
))
def ema_crossover_strategy(df: pd.DataFrame) -> pd.Series:
    from lib.gumloop_trading import compute_ema
    ema9 = compute_ema(df['close'], 9)
    ema21 = compute_ema(df['close'], 21)
    avg_vol = df['volume'].rolling(20).mean()

    signals = pd.Series(0, index=df.index)
    # Buy: EMA9 crosses above EMA21 + volume > 1.5x average
    buy_cond = (ema9 > ema21) & (ema9.shift(1) <= ema21.shift(1)) & (df['volume'] > avg_vol * 1.5)
    # Sell: EMA9 crosses below EMA21
    sell_cond = (ema9 < ema21) & (ema9.shift(1) >= ema21.shift(1))
    signals.loc[buy_cond] = 1
    signals.loc[sell_cond] = -1
    return signals

# ── Strategy 2: RSI 2.0 Oversold Bounce ────────────────────

@register("rsi_bounce", StrategyMeta(
    name="RSI 2 Oversold Bounce",
    description="Buy when RSI(2) drops below 5 (extreme oversold) then crosses above 10",
    timeframe="5m/15m",
    expected_win_rate=0.58,
    avg_holding_period="15-60 min",
    best_market="ranging",
    risk_level="high",
))
def rsi_bounce_strategy(df: pd.DataFrame) -> pd.Series:
    from lib.gumloop_trading import compute_rsi
    rsi2 = compute_rsi(df['close'], 2)

    signals = pd.Series(0, index=df.index)
    # Buy: RSI(2) was below 5 and crosses above 10
    buy_cond = (rsi2 > 10) & (rsi2.shift(1) <= 5)
    # Sell: RSI(2) crosses above 80 (overbought)
    sell_cond = rsi2 > 80
    signals.loc[buy_cond] = 1
    signals.loc[sell_cond] = -1
    return signals

# ── Strategy 3: VWAP Mean Reversion ────────────────────────

@register("vwap_reversion", StrategyMeta(
    name="VWAP Mean Reversion",
    description="Buy when price is 2% below VWAP, sell when 2% above, with volume confirmation",
    timeframe="5m/15m",
    expected_win_rate=0.65,
    avg_holding_period="30-120 min",
    best_market="ranging",
    risk_level="low",
))
def vwap_reversion_strategy(df: pd.DataFrame) -> pd.Series:
    from lib.gumloop_trading import compute_vwap
    vwap = compute_vwap(df)

    signals = pd.Series(0, index=df.index)
    deviation = (df['close'] - vwap) / vwap

    buy_cond = (deviation < -0.02) & (df['volume'] > df['volume'].rolling(20).mean())
    sell_cond = (deviation > 0.02) & (df['volume'] > df['volume'].rolling(20).mean())
    signals.loc[buy_cond] = 1
    signals.loc[sell_cond] = -1
    return signals

# ── Strategy 4: MACD Momentum Scalp ────────────────────────

@register("macd_scalp", StrategyMeta(
    name="MACD Momentum Scalp",
    description="Scalp when MACD histogram turns positive with increasing momentum",
    timeframe="1m/5m",
    expected_win_rate=0.55,
    avg_holding_period="5-20 min",
    best_market="trending",
    risk_level="high",
))
def macd_scalp_strategy(df: pd.DataFrame) -> pd.Series:
    from lib.gumloop_trading import compute_macd
    macd, signal, hist = compute_macd(df['close'])

    signals = pd.Series(0, index=df.index)
    # Buy: histogram turns positive and rising
    buy_cond = (hist > 0) & (hist > hist.shift(1)) & (hist.shift(1) <= 0)
    # Sell: histogram turns negative and falling
    sell_cond = (hist < 0) & (hist < hist.shift(1)) & (hist.shift(1) >= 0)
    signals.loc[buy_cond] = 1
    signals.loc[sell_cond] = -1
    return signals

# ── Strategy 5: Bollinger Squeeze Breakout ─────────────────

@register("bollinger_squeeze", StrategyMeta(
    name="Bollinger Squeeze Breakout",
    description="Buy when Bollinger Bands contract then expand with breakout above upper band",
    timeframe="15m/1h",
    expected_win_rate=0.60,
    avg_holding_period="1-4 hours",
    best_market="volatile",
    risk_level="medium",
))
def bollinger_squeeze_strategy(df: pd.DataFrame) -> pd.Series:
    from lib.gumloop_trading import compute_bollinger
    ma, upper, lower = compute_bollinger(df['close'], 20, 2)
    bandwidth = (upper - lower) / ma
    avg_bandwidth = bandwidth.rolling(50).mean()

    signals = pd.Series(0, index=df.index)
    squeeze = bandwidth < avg_bandwidth * 0.8

    # Buy: breakout above upper band after squeeze
    buy_cond = (df['close'] > upper) & squeeze.shift(1) & (df['volume'] > df['volume'].rolling(20).mean() * 1.5)
    # Sell: breakdown below lower band after squeeze
    sell_cond = (df['close'] < lower) & squeeze.shift(1) & (df['volume'] > df['volume'].rolling(20).mean() * 1.5)

    signals.loc[buy_cond] = 1
    signals.loc[sell_cond] = -1
    return signals

# ── Strategy 6: Ichimoku Cloud Trend ───────────────────────

@register("ichimoku_trend", StrategyMeta(
    name="Ichimoku Cloud Trend",
    description="Trade in direction of Ichimoku cloud: buy above cloud, sell below cloud",
    timeframe="1h/4h",
    expected_win_rate=0.68,
    avg_holding_period="6-48 hours",
    best_market="trending",
    risk_level="low",
))
def ichimoku_trend_strategy(df: pd.DataFrame) -> pd.Series:
    from lib.gumloop_trading import compute_ichimoku
    ichi = compute_ichimoku(df)

    signals = pd.Series(0, index=df.index)
    cloud_top = pd.concat([ichi['senkou_a'], ichi['senkou_b']], axis=1).max(axis=1)
    cloud_bot = pd.concat([ichi['senkou_a'], ichi['senkou_b']], axis=1).min(axis=1)

    buy_cond = (df['close'] > cloud_top) & (ichi['tenkan'] > ichi['kijun'])
    sell_cond = (df['close'] < cloud_bot) & (ichi['tenkan'] < ichi['kijun'])

    signals.loc[buy_cond] = 1
    signals.loc[sell_cond] = -1
    return signals

# ── Helpers ────────────────────────────────────────────────

def list_strategies() -> List[Dict]:
    return [
        {"name": name, **meta.__dict__}
        for name, (_, meta) in STRATEGIES.items()
    ]

def run_all_strategies(df: pd.DataFrame) -> Dict[str, pd.Series]:
    return {name: func(df) for name, (func, _) in STRATEGIES.items()}

def ensemble_signal(strategies: Dict[str, pd.Series], min_votes: int = 3) -> pd.Series:
    """Combine multiple strategy signals. At least min_votes must agree."""
    votes = pd.concat(strategies, axis=1)
    buy_votes = (votes == 1).sum(axis=1)
    sell_votes = (votes == -1).sum(axis=1)
    signals = pd.Series(0, index=votes.index)
    signals.loc[buy_votes >= min_votes] = 1
    signals.loc[sell_votes >= min_votes] = -1
    return signals
