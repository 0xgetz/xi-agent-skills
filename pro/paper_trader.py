#!/usr/bin/env python3
"""
paper_trader.py — Connect the orchestrator to LIVE market data for paper trading.

This is the bridge that turns the verified `pro/` system into something that
actually trades (on paper): live data → orchestrator decision → realistic fill
simulation → persistent virtual portfolio → stop/target monitoring → reporting,
with drawdown / daily-PnL / exposure fed back into the orchestrator's risk gates.

No real money. No exchange keys. Pure paper trading for validation before any
real capital is ever risked — exactly how a professional tests a system.

Data sources (no API key required):
    • yfinance   — primary, full OHLCV for crypto (BTC-USD) and stocks (AAPL)
    • CoinGecko  — fallback spot price

Usage:
    PYTHONPATH=. python pro/paper_trader.py --symbols BTC-USD ETH-USD --capital 10000
    PYTHONPATH=. python pro/paper_trader.py --status        # show portfolio
    PYTHONPATH=. python pro/paper_trader.py --reset         # wipe paper state
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from pro.orchestrator import TradingSystem, SystemConfig, Decision

STATE_FILE = os.environ.get("PAPER_STATE_FILE", os.path.join(ROOT, "paper_state.json"))


# ════════════════════════════════════════════════════════════════════
#  Live market data
# ════════════════════════════════════════════════════════════════════

class LiveMarketData:
    """Fetch live OHLCV. yfinance primary (works for crypto + stocks), CoinGecko fallback."""

    CG_IDS = {"BTC-USD": "bitcoin", "ETH-USD": "ethereum", "SOL-USD": "solana",
              "BNB-USD": "binancecoin", "XRP-USD": "ripple", "ADA-USD": "cardano"}

    def fetch_ohlcv(self, symbol: str, period: str = "3mo", interval: str = "1d") -> Optional[pd.DataFrame]:
        df = self._fetch_yfinance(symbol, period, interval)
        if df is not None and len(df) >= 50:
            return df
        return None

    def _fetch_yfinance(self, symbol: str, period: str, interval: str) -> Optional[pd.DataFrame]:
        try:
            import yfinance as yf
            df = yf.Ticker(symbol).history(period=period, interval=interval)
            if df is None or df.empty:
                return None
            df.columns = [c.lower() for c in df.columns]
            cols = ["open", "high", "low", "close", "volume"]
            if not all(c in df.columns for c in cols):
                return None
            return df[cols].dropna()
        except Exception as exc:  # noqa: BLE001
            print(f"  [data] yfinance error for {symbol}: {exc}")
            return None

    def spot_price(self, symbol: str) -> Optional[float]:
        """Latest spot price — try yfinance fast_info, then CoinGecko."""
        try:
            import yfinance as yf
            fi = yf.Ticker(symbol).fast_info
            px = float(fi.get("last_price") or fi.get("lastPrice") or 0)
            if px > 0:
                return px
        except Exception:  # noqa: BLE001
            pass
        cg = self.CG_IDS.get(symbol)
        if cg:
            try:
                import requests
                r = requests.get(
                    f"https://api.coingecko.com/api/v3/simple/price?ids={cg}&vs_currencies=usd",
                    timeout=10)
                if r.status_code == 200:
                    return float(r.json()[cg]["usd"])
            except Exception:  # noqa: BLE001
                pass
        return None


# ════════════════════════════════════════════════════════════════════
#  Virtual portfolio
# ════════════════════════════════════════════════════════════════════

@dataclass
class PaperPosition:
    symbol: str
    side: str
    entry_price: float
    size_units: float
    size_usd: float
    stop_loss: float
    take_profit: float
    opened_at: str
    regime: str = ""
    confidence: float = 0.0

    def unrealized_pnl(self, price: float) -> float:
        diff = (price - self.entry_price) * self.size_units
        return diff if self.side == "long" else -diff


@dataclass
class PaperState:
    initial_capital: float
    cash: float
    realized_pnl: float = 0.0
    peak_equity: float = 0.0
    day: str = ""
    daily_pnl: float = 0.0
    positions: List[dict] = field(default_factory=list)
    closed_trades: List[dict] = field(default_factory=list)
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005


class PaperPortfolio:
    """Persistent virtual portfolio with realistic fills."""

    def __init__(self, capital: float = 10_000.0):
        self.state = self._load(capital)

    # ── persistence ──
    def _load(self, capital: float) -> PaperState:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    d = json.load(f)
                return PaperState(**d)
            except Exception:  # noqa: BLE001
                pass
        return PaperState(initial_capital=capital, cash=capital, peak_equity=capital,
                          day=datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    def save(self):
        with open(STATE_FILE, "w") as f:
            json.dump(asdict(self.state), f, indent=2)

    # ── helpers ──
    def _roll_day(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.state.day != today:
            self.state.day = today
            self.state.daily_pnl = 0.0

    def positions(self) -> List[PaperPosition]:
        return [PaperPosition(**p) for p in self.state.positions]

    def open_symbols(self) -> set:
        return {p["symbol"] for p in self.state.positions}

    def equity(self, prices: Dict[str, float]) -> float:
        eq = self.state.cash
        for p in self.positions():
            px = prices.get(p.symbol, p.entry_price)
            eq += p.size_units * px if p.side == "long" else p.size_usd + p.unrealized_pnl(px)
        return eq

    def drawdown(self, prices: Dict[str, float]) -> float:
        eq = self.equity(prices)
        self.state.peak_equity = max(self.state.peak_equity, eq)
        if self.state.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.state.peak_equity - eq) / self.state.peak_equity)

    def exposure(self, prices: Dict[str, float]) -> float:
        eq = self.equity(prices) or 1.0
        used = sum(p.size_usd for p in self.positions())
        return used / eq

    # ── trading ──
    def open(self, symbol: str, side: str, price: float, size_usd: float,
             sl: float, tp: float, regime: str, conf: float) -> Optional[PaperPosition]:
        self._roll_day()
        fill = price * (1 + self.state.slippage_pct) if side == "long" else price * (1 - self.state.slippage_pct)
        fee = size_usd * self.state.fee_pct
        if size_usd + fee > self.state.cash:
            size_usd = max(0.0, self.state.cash - fee)
            if size_usd <= 0:
                return None
        units = size_usd / fill
        self.state.cash -= (size_usd + fee)
        pos = PaperPosition(symbol, side, fill, units, size_usd, sl, tp,
                            datetime.now(timezone.utc).isoformat(), regime, conf)
        self.state.positions.append(asdict(pos))
        return pos

    def close(self, pos: PaperPosition, price: float, reason: str) -> float:
        self._roll_day()
        fill = price * (1 - self.state.slippage_pct) if pos.side == "long" else price * (1 + self.state.slippage_pct)
        gross = pos.unrealized_pnl(fill)
        fee = pos.size_units * fill * self.state.fee_pct
        pnl = gross - fee
        self.state.cash += pos.size_usd + pnl
        self.state.realized_pnl += pnl
        self.state.daily_pnl += pnl
        self.state.positions = [p for p in self.state.positions if not (
            p["symbol"] == pos.symbol and abs(p["entry_price"] - pos.entry_price) < 1e-9)]
        self.state.closed_trades.append({
            "symbol": pos.symbol, "side": pos.side, "entry": pos.entry_price,
            "exit": fill, "pnl": round(pnl, 2),
            "pnl_pct": round(pnl / pos.size_usd * 100, 2) if pos.size_usd else 0,
            "reason": reason, "closed_at": datetime.now(timezone.utc).isoformat(),
        })
        return pnl


# ════════════════════════════════════════════════════════════════════
#  Paper trader (ties orchestrator + live data + portfolio)
# ════════════════════════════════════════════════════════════════════

class PaperTrader:
    def __init__(self, symbols: List[str], capital: float = 10_000.0,
                 config: Optional[SystemConfig] = None):
        self.symbols = symbols
        self.data = LiveMarketData()
        self.portfolio = PaperPortfolio(capital)
        self.system = TradingSystem(config or SystemConfig(capital=capital))

    def _sync_risk_state(self, prices: Dict[str, float]):
        """Feed live drawdown / daily-PnL / exposure into the orchestrator's risk gates."""
        self.system.update_state(
            daily_pnl=self.portfolio.state.daily_pnl,
            drawdown=self.portfolio.drawdown(prices),
            open_exposure=self.portfolio.exposure(prices),
        )

    def run_cycle(self, verbose: bool = True) -> dict:
        """One full paper-trading cycle: data → monitor stops → decide → execute → report."""
        log = []
        # 1) fetch market data + prices
        market: Dict[str, pd.DataFrame] = {}
        prices: Dict[str, float] = {}
        for sym in self.symbols:
            df = self.data.fetch_ohlcv(sym)
            if df is not None:
                market[sym] = df
                prices[sym] = float(df["close"].iloc[-1])
        if not market:
            return {"error": "no market data fetched"}

        if verbose:
            print(f"\n📡 Live data: {', '.join(f'{s}=${prices[s]:,.2f}' for s in prices)}")

        # 2) monitor existing positions (stops / targets)
        for pos in self.portfolio.positions():
            px = prices.get(pos.symbol)
            if px is None:
                continue
            hit = None
            if pos.side == "long":
                if px <= pos.stop_loss: hit = "stop_loss"
                elif px >= pos.take_profit: hit = "take_profit"
            else:
                if px >= pos.stop_loss: hit = "stop_loss"
                elif px <= pos.take_profit: hit = "take_profit"
            if hit:
                pnl = self.portfolio.close(pos, px, hit)
                msg = f"🔴 CLOSE {pos.symbol} ({hit}) → PnL ${pnl:+,.2f}"
                log.append(msg)
                if verbose: print(f"  {msg}")

        # 3) sync risk state, then ask orchestrator for decisions
        self._sync_risk_state(prices)
        open_syms = self.portfolio.open_symbols()
        decisions = self.system.scan({s: df for s, df in market.items() if s not in open_syms})

        # 4) execute new entries
        for d in decisions:
            if d.decision not in (Decision.ENTER_LONG, Decision.ENTER_SHORT):
                continue
            size_usd = self.portfolio.equity(prices) * d.size_fraction
            side = "long" if d.decision == Decision.ENTER_LONG else "short"
            pos = self.portfolio.open(d.symbol, side, d.entry_price, size_usd,
                                      d.stop_loss, d.take_profit, d.regime, d.confidence)
            if pos:
                msg = (f"🟢 OPEN {side.upper()} {d.symbol} @ ${pos.entry_price:,.2f} "
                       f"| size ${size_usd:,.0f} ({d.size_fraction:.1%}) | "
                       f"SL ${d.stop_loss:,.2f} TP ${d.take_profit:,.2f} | conf {d.confidence:.0%}")
                log.append(msg)
                if verbose: print(f"  {msg}")

        self.portfolio.save()

        # 5) report
        eq = self.portfolio.equity(prices)
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "equity": round(eq, 2),
            "cash": round(self.portfolio.state.cash, 2),
            "realized_pnl": round(self.portfolio.state.realized_pnl, 2),
            "total_return_pct": round((eq / self.portfolio.state.initial_capital - 1) * 100, 2),
            "drawdown_pct": round(self.portfolio.drawdown(prices) * 100, 2),
            "open_positions": len(self.portfolio.state.positions),
            "closed_trades": len(self.portfolio.state.closed_trades),
            "actions": log,
        }
        if verbose:
            self._print_report(report)
        return report

    def _print_report(self, r: dict):
        print(f"\n┌─ 📊 PAPER PORTFOLIO")
        print(f"│  Equity: ${r['equity']:,.2f}  ({r['total_return_pct']:+.2f}%)")
        print(f"│  Cash: ${r['cash']:,.2f}  |  Realized PnL: ${r['realized_pnl']:+,.2f}")
        print(f"│  Drawdown: {r['drawdown_pct']:.2f}%  |  Open: {r['open_positions']}  |  Closed: {r['closed_trades']}")
        print(f"└{'─'*42}")

    def status(self) -> dict:
        prices = {}
        for sym in self.symbols:
            px = self.data.spot_price(sym)
            if px: prices[sym] = px
        eq = self.portfolio.equity(prices)
        print(f"\n📊 PAPER PORTFOLIO STATUS")
        print(f"   Equity: ${eq:,.2f} ({(eq/self.portfolio.state.initial_capital-1)*100:+.2f}%)")
        print(f"   Cash: ${self.portfolio.state.cash:,.2f} | Realized: ${self.portfolio.state.realized_pnl:+,.2f}")
        for p in self.portfolio.positions():
            px = prices.get(p.symbol, p.entry_price)
            print(f"   • {p.side.upper()} {p.symbol} @ ${p.entry_price:,.2f} → ${px:,.2f} "
                  f"(PnL ${p.unrealized_pnl(px):+,.2f})")
        return {"equity": eq, "positions": len(self.portfolio.state.positions)}


# ════════════════════════════════════════════════════════════════════
#  CLI
# ════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="XIBot Pro paper trader (live data, no real money)")
    ap.add_argument("--symbols", nargs="+", default=["BTC-USD", "ETH-USD", "SOL-USD"])
    ap.add_argument("--capital", type=float, default=10_000.0)
    ap.add_argument("--status", action="store_true", help="show portfolio and exit")
    ap.add_argument("--reset", action="store_true", help="wipe paper state and exit")
    args = ap.parse_args()

    if args.reset:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        print("🧹 Paper state reset.")
        return

    trader = PaperTrader(args.symbols, args.capital)
    if args.status:
        trader.status()
    else:
        trader.run_cycle()


if __name__ == "__main__":
    main()
