import pandas as pd, numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from datetime import datetime, timezone
import json, hashlib

@dataclass
class Trade:
    entry_time: datetime; exit_time: datetime
    entry_price: float; exit_price: float
    size: float; pnl: float; pnl_pct: float
    side: str  # long/short
    reason: str = ""

    def __post_init__(self):
        self.trade_id = hashlib.md5(f"{self.entry_time}{self.exit_time}{self.entry_price}".encode()).hexdigest()[:12]

@dataclass
class BacktestConfig:
    initial_capital: float = 10000.0
    position_size_pct: float = 0.02  # 2% risk per trade
    max_leverage: float = 1.0
    fee_pct: float = 0.001  # 0.1% per side
    slippage_pct: float = 0.001  # 0.1% slippage
    stop_loss_pct: float = 0.02  # 2% stop
    take_profit_pct: float = 0.04  # 4% target

class BacktestEngine:
    """Professional-grade backtester with realistic market assumptions."""

    def __init__(self, config: BacktestConfig = None):
        self.cfg = config or BacktestConfig()
        self.trades: List[Trade] = []
        self.equity_curve: List[float] = []

    def run(self, df: pd.DataFrame, signal_col: str, price_col: str = "close",
            stop_col: Optional[str] = None, take_col: Optional[str] = None) -> Dict:
        """
        signal_col: 1=buy, -1=sell, 0=hold
        """
        capital = self.cfg.initial_capital
        position = 0.0
        entry_price = 0.0
        entry_time = None
        side = None

        self.trades = []
        equity = [capital]

        for i in range(1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i-1]
            price = row[price_col]

            # Check stop loss / take profit on existing position
            if position != 0:
                pnl_pct = (price - entry_price) / entry_price
                if side == "short":
                    pnl_pct = -pnl_pct

                sl = self.cfg.stop_loss_pct
                tp = self.cfg.take_profit_pct

                if pnl_pct <= -sl or pnl_pct >= tp:
                    # Close trade
                    exit_val = position * price * (1 - self.cfg.fee_pct - self.cfg.slippage_pct)
                    pnl = exit_val - (position * entry_price)
                    capital = position * price + pnl - (position * price * self.cfg.fee_pct)

                    self.trades.append(Trade(
                        entry_time=entry_time, exit_time=row.name,
                        entry_price=entry_price, exit_price=price,
                        size=position, pnl=pnl, pnl_pct=pnl_pct,
                        side=side, reason=f"SL/TP at {pnl_pct:.1%}"
                    ))
                    position = 0; side = None; entry_price = 0

            # Check signal
            signal = row[signal_col]

            if signal == 1 and position == 0:  # BUY
                size = (capital * self.cfg.position_size_pct) / price
                entry_price = price * (1 + self.cfg.slippage_pct)
                entry_time = row.name
                capital -= size * entry_price * (1 + self.cfg.fee_pct)
                position = size
                side = "long"

            elif signal == -1 and position == 0:  # SELL
                size = (capital * self.cfg.position_size_pct) / price
                entry_price = price * (1 - self.cfg.slippage_pct)
                entry_time = row.name
                capital += size * entry_price * (1 - self.cfg.fee_pct)
                position = -size
                side = "short"

            elif signal == 0 and position != 0:  # EXIT
                exit_val = position * price * (1 - self.cfg.fee_pct)
                pnl = exit_val - (position * entry_price)
                capital = position * price + pnl - (position * price * self.cfg.fee_pct)

                self.trades.append(Trade(
                    entry_time=entry_time, exit_time=row.name,
                    entry_price=entry_price, exit_price=price,
                    size=abs(position), pnl=pnl, pnl_pct=pnl / (abs(position) * entry_price),
                    side=side, reason="Signal exit"
                ))
                position = 0; side = None; entry_price = 0

            equity.append(capital + abs(position) * price if position != 0 else capital)

        self.equity_curve = equity
        return self._report(df)

    def _report(self, df: pd.DataFrame) -> Dict:
        if not self.trades:
            return {"total_trades": 0, "win_rate": 0, "total_pnl": 0, "sharpe": 0}

        total_pnl = sum(t.pnl for t in self.trades)
        wins = sum(1 for t in self.trades if t.pnl > 0)
        losses = sum(1 for t in self.trades if t.pnl <= 0)
        win_rate = wins / len(self.trades) if self.trades else 0

        returns = pd.Series(self.equity_curve).pct_change().dropna()
        sharpe = returns.mean() / returns.std() * np.sqrt(365) if returns.std() > 0 else 0

        max_drawdown = 0
        peak = self.equity_curve[0]
        for val in self.equity_curve:
            if val > peak: peak = val
            dd = (peak - val) / peak
            if dd > max_drawdown: max_drawdown = dd

        avg_win = sum(t.pnl for t in self.trades if t.pnl > 0) / wins if wins else 0
        avg_loss = sum(t.pnl for t in self.trades if t.pnl <= 0) / losses if losses else 0
        profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        return {
            "total_trades": len(self.trades),
            "win_rate": round(win_rate, 3),
            "total_pnl": round(total_pnl, 2),
            "total_return_pct": round(total_pnl / self.cfg.initial_capital * 100, 2),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_pct": round(max_drawdown * 100, 2),
            "profit_factor": round(profit_factor, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "final_equity": round(self.equity_curve[-1], 2),
        }

# ── Quick strategy definitions ─────────────────────────────

def momentum_breakout_strategy(df: pd.DataFrame, lookback: int = 20, threshold: float = 0.05) -> pd.Series:
    """Buy when price breaks above 20-day high with volume confirmation."""
    signals = pd.Series(0, index=df.index)
    highest = df['close'].rolling(lookback).max().shift(1)
    avg_vol = df['volume'].rolling(lookback).mean().shift(1)
    signals.loc[(df['close'] > highest) & (df['volume'] > avg_vol * 1.5)] = 1
    signals.loc[(df['close'] < df['close'].rolling(lookback).min().shift(1))] = -1
    return signals

def mean_reversion_strategy(df: pd.DataFrame, period: int = 14, std: float = 2.0) -> pd.Series:
    """Buy when price touches lower Bollinger, sell when touches upper."""
    sma = df['close'].rolling(period).mean()
    sd = df['close'].rolling(period).std()
    signals = pd.Series(0, index=df.index)
    signals.loc[df['close'] <= sma - std * sd] = 1
    signals.loc[df['close'] >= sma + std * sd] = -1
    return signals

def rsi_divergence_strategy(df: pd.DataFrame, rsi_period: int = 14) -> pd.Series:
    """Trade RSI divergences — buy bullish divergence, sell bearish divergence."""
    from lib.gumloop_trading import compute_rsi
    rsi = compute_rsi(df['close'], rsi_period)
    signals = pd.Series(0, index=df.index)

    for i in range(2, len(df)):
        # Bullish divergence: lower low in price, higher low in RSI
        if (df['close'].iloc[i] < df['close'].iloc[i-1] < df['close'].iloc[i-2] and
            rsi.iloc[i] > rsi.iloc[i-1] > rsi.iloc[i-2]):
            signals.iloc[i] = 1
        # Bearish divergence: higher high in price, lower high in RSI
        if (df['close'].iloc[i] > df['close'].iloc[i-1] > df['close'].iloc[i-2] and
            rsi.iloc[i] < rsi.iloc[i-1] < rsi.iloc[i-2]):
            signals.iloc[i] = -1
    return signals

def multi_timeframe_strategy(df: pd.DataFrame) -> pd.Series:
    """Combine trend (50 EMA) + momentum (RSI > 50) + volume confirmation."""
    from lib.gumloop_trading import compute_ema, compute_rsi
    ema50 = compute_ema(df['close'], 50)
    rsi = compute_rsi(df['close'], 14)
    avg_vol = df['volume'].rolling(20).mean()
    signals = pd.Series(0, index=df.index)
    signals.loc[(df['close'] > ema50) & (rsi > 50) & (rsi < 70) & (df['volume'] > avg_vol)] = 1
    signals.loc[(df['close'] < ema50) & (rsi < 50) & (rsi > 30) & (df['volume'] > avg_vol)] = -1
    return signals
