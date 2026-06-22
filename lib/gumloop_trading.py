"""
gumloop_trading — Shared trading analysis library for Gumloop agent skills.
Provides core functions used by 100+ trading skill Python scripts.
"""
import pandas as pd, numpy as np, requests, json, os, time
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, List

# ── OHLCV helpers ──────────────────────────────────────────
def validate_ohlcv(df: pd.DataFrame) -> bool:
    """Ensure a DataFrame has required OHLCV columns."""
    cols = {"open","high","low","close","volume"}
    return cols.issubset(df.columns)

def compute_sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()

def compute_ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()

def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl, hc, lc = df.high-df.low, (df.high-df.close.shift()).abs(), (df.low-df.close.shift()).abs()
    tr = pd.concat([hl,hc,lc],axis=1).max(axis=1)
    return tr.rolling(period).mean()

def compute_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0,np.nan)
    return 100 - (100 / (1 + rs))

def compute_macd(series: pd.Series, fast=12, slow=26, sig=9):
    efast = compute_ema(series, fast)
    eslow = compute_ema(series, slow)
    macd = efast - eslow
    signal = compute_ema(macd, sig)
    return macd, signal, macd - signal

def compute_bollinger(series: pd.Series, period=20, std_dev=2):
    ma = compute_sma(series, period)
    std = series.rolling(period).std()
    return ma, ma + std_dev*std, ma - std_dev*std

def compute_stochastic(df: pd.DataFrame, k=14, d=3):
    low_k = df.low.rolling(k).min()
    high_k = df.high.rolling(k).max()
    k_val = 100 * (df.close - low_k) / (high_k - low_k).replace(0,np.nan)
    d_val = k_val.rolling(d).mean()
    return k_val, d_val

def compute_adx(df: pd.DataFrame, period: int = 14):
    up = df.high.diff(); down = -df.low.diff()
    tr = pd.concat([df.high-df.low,(df.high-df.close.shift()).abs(),(df.low-df.close.shift()).abs()],axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    dm_plus = up.where((up>down)&(up>0),0).rolling(period).mean()
    dm_minus = down.where((down>up)&(down>0),0).rolling(period).mean()
    di_plus = 100 * dm_plus / atr.replace(0,np.nan)
    di_minus = 100 * dm_minus / atr.replace(0,np.nan)
    dx = 100 * (di_plus-di_minus).abs() / (di_plus+di_minus).replace(0,np.nan)
    return dx.rolling(period).mean(), di_plus, di_minus

def compute_obv(df: pd.DataFrame):
    return (df.volume * ((df.close > df.close.shift()).astype(int)*2-1)).cumsum()

def compute_vwap(df: pd.DataFrame):
    return (df.volume * (df.high+df.low+df.close)/3).cumsum() / df.volume.cumsum().replace(0,np.nan)

def compute_ichimoku(df: pd.DataFrame, t=9, k=26, s=52):
    ten = (df.high.rolling(t).max() + df.low.rolling(t).min())/2
    kij = (df.high.rolling(k).max() + df.low.rolling(k).min())/2
    sa = (ten+kij)/2
    sb = (df.high.rolling(s).max() + df.low.rolling(s).min())/2
    return {"tenkan":ten,"kijun":kij,"senkou_a":sa,"senkou_b":sb,"chikou":df.close.shift(-k)}

def count_signals(df: pd.DataFrame, n: int = 20) -> int:
    """Count bullish signals from the last n bars using common patterns."""
    count = 0
    close, high, low = df.close, df.high, df.low
    # Higher low
    if len(df) >= 3 and low.iloc[-1] > low.iloc[-2]: count += 1
    # Close above open
    if close.iloc[-1] > df.open.iloc[-1]: count += 1
    # RSI positive
    rsi = compute_rsi(close, 14)
    if not rsi.isna().all() and rsi.iloc[-1] > 50: count += 1
    # MACD above zero
    macd,_,_ = compute_macd(close)
    if not macd.isna().all() and macd.iloc[-1] > 0: count += 1
    return count