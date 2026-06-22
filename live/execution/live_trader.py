import pandas as pd, numpy as np, os, json, time, requests
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Dict, List
import hashlib, hmac

# ── Configuration ──────────────────────────────────────────

@dataclass
class TradingConfig:
    """All config loaded from env vars for security."""
    capital_usd: float = float(os.environ.get("CAPITAL_USD", "500"))
    max_positions: int = int(os.environ.get("MAX_POSITIONS", "3"))
    risk_per_trade_pct: float = float(os.environ.get("RISK_PER_TRADE", "0.02"))
    max_daily_loss_pct: float = float(os.environ.get("MAX_DAILY_LOSS", "0.05"))
    take_profit_pct: float = float(os.environ.get("TAKE_PROFIT", "0.03"))
    stop_loss_pct: float = float(os.environ.get("STOP_LOSS", "0.015"))
    cooldown_minutes: int = int(os.environ.get("COOLDOWN", "60"))

    # Exchange API (if using real exchange)
    exchange: str = os.environ.get("EXCHANGE", "binance")
    api_key: Optional[str] = None  # loaded from secret
    api_secret: Optional[str] = None

    # Telegram
    telegram_token: Optional[str] = None
    telegram_chat: Optional[str] = None

    def validate(self):
        assert self.capital_usd > 0, "CAPITAL_USD must be > 0"
        assert 0 < self.risk_per_trade_pct <= 0.05, "Max 5% risk per trade"
        assert self.max_positions >= 1

# ── Position Manager ───────────────────────────────────────

@dataclass
class Position:
    symbol: str
    side: str  # long/short
    entry_price: float
    size_usd: float
    size_units: float
    entry_time: datetime
    stop_loss: float
    take_profit: float
    pnl: float = 0.0
    status: str = "open"  # open / closed

    @property
    def pnl_pct(self) -> float:
        return self.pnl / self.size_usd if self.size_usd else 0.0

class PositionManager:
    """Manages open positions, risk limits, and daily PnL tracking."""

    def __init__(self, config: TradingConfig):
        self.cfg = config
        self.positions: List[Position] = []
        self.closed_trades: List[Position] = []
        self.daily_pnl: float = 0.0
        self.last_trade_time: Dict[str, datetime] = {}  # symbol -> last trade time
        self._init_pnl_file()

    def _init_pnl_file(self):
        self.pnl_file = "daily_pnl.json"
        if os.path.exists(self.pnl_file):
            try:
                with open(self.pnl_file) as f:
                    data = json.load(f)
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                if data.get("date") == today:
                    self.daily_pnl = data.get("pnl", 0.0)
            except: pass

    def can_open(self, symbol: str) -> bool:
        """Check if we can open a new position based on risk rules."""
        # Position limit
        if len(self.positions) >= self.cfg.max_positions:
            return False
        # Daily loss limit
        if self.daily_pnl <= -self.cfg.capital_usd * self.cfg.max_daily_loss_pct:
            return False  # hit daily loss limit
        # Cooldown
        if symbol in self.last_trade_time:
            elapsed = (datetime.now(timezone.utc) - self.last_trade_time[symbol]).total_seconds() / 60
            if elapsed < self.cfg.cooldown_minutes:
                return False
        return True

    def open_position(self, symbol: str, side: str, price: float, reason: str = "") -> Optional[Position]:
        if not self.can_open(symbol):
            return None

        size_usd = self.cfg.capital_usd * self.cfg.risk_per_trade_pct * 100  # 2% of capital
        size_units = size_usd / price

        sl = price * (1 - self.cfg.stop_loss_pct) if side == "long" else price * (1 + self.cfg.stop_loss_pct)
        tp = price * (1 + self.cfg.take_profit_pct) if side == "long" else price * (1 - self.cfg.take_profit_pct)

        pos = Position(
            symbol=symbol, side=side, entry_price=price,
            size_usd=size_usd, size_units=size_units,
            entry_time=datetime.now(timezone.utc),
            stop_loss=sl, take_profit=tp
        )
        self.positions.append(pos)
        self.last_trade_time[symbol] = datetime.now(timezone.utc)
        self._send_alert(f"🟢 **{side.upper()}** {symbol}\nEntry: ${price:.4f}\nSize: ${size_usd:.0f}\nSL: ${sl:.4f}\nTP: ${tp:.4f}\nReason: {reason}")
        return pos

    def check_stops(self, prices: Dict[str, float]) -> List[Position]:
        """Check all positions against current prices. Return closed positions."""
        closed = []
        for pos in list(self.positions):  # iterate copy
            price = prices.get(pos.symbol)
            if not price: continue

            pnl = (price - pos.entry_price) * pos.size_units
            if pos.side == "short":
                pnl = -pnl
            pos.pnl = pnl

            # Check stop loss / take profit
            if pos.side == "long":
                if price <= pos.stop_loss or price >= pos.take_profit:
                    pos.status = "closed"
                    self.daily_pnl += pnl
                    closed.append(pos)
                    self.positions.remove(pos)
                    self.closed_trades.append(pos)
                    self._send_alert(f"🔴 **CLOSED** {pos.symbol}\nPnL: ${pnl:.2f} ({pos.pnl_pct:.1%})\nExit: ${price:.4f}")
            else:  # short
                if price >= pos.stop_loss or price <= pos.take_profit:
                    pos.status = "closed"
                    self.daily_pnl += pnl
                    closed.append(pos)
                    self.positions.remove(pos)
                    self.closed_trades.append(pos)
                    self._send_alert(f"🔴 **CLOSED** {pos.symbol}\nPnL: ${pnl:.2f} ({pos.pnl_pct:.1%})\nExit: ${price:.4f}")

        self._save_daily_pnl()
        return closed

    def _send_alert(self, text: str):
        if self.cfg.telegram_token and self.cfg.telegram_chat:
            try:
                requests.post(
                    f"https://api.telegram.org/bot{self.cfg.telegram_token}/sendMessage",
                    json={"chat_id": self.cfg.telegram_chat, "text": text, "parse_mode": "Markdown"},
                    timeout=5
                )
            except: pass

    def _save_daily_pnl(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(self.pnl_file, "w") as f:
            json.dump({"date": today, "pnl": self.daily_pnl}, f)

    def summary(self) -> str:
        """Generate a performance summary."""
        total_pnl = sum(t.pnl for t in self.closed_trades)
        wins = sum(1 for t in self.closed_trades if t.pnl > 0)
        return (f"📊 **Daily PnL:** ${self.daily_pnl:.2f}\n"
                f"   **Open Positions:** {len(self.positions)}\n"
                f"   **Total Trades:** {len(self.closed_trades)}\n"
                f"   **Wins:** {wins} | **Win Rate:** {wins/len(self.closed_trades):.0%}" if self.closed_trades else "No closed trades")

# ── Market Data Feed ────────────────────────────────────────

class MarketDataFeed:
    """Fetches real-time prices from multiple sources."""

    def __init__(self):
        self.sources = {
            "coingecko": self._fetch_coingecko,
            "binance": self._fetch_binance,
            "dexscreener": self._fetch_dexscreener,
        }

    def _fetch_coingecko(self, symbol: str) -> Optional[float]:
        try:
            # symbol must be like "bitcoin"
            url = f"https://api.coingecko.com/api/v3/simple/price?ids={symbol}&vs_currencies=usd"
            data = requests.get(url, timeout=5).json()
            return data.get(symbol, {}).get("usd")
        except: return None

    def _fetch_binance(self, symbol: str) -> Optional[float]:
        try:
            symbol = symbol.upper() + "USDT"
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            data = requests.get(url, timeout=5).json()
            return float(data.get("price", 0))
        except: return None

    def _fetch_dexscreener(self, chain: str, pair: str) -> Optional[Dict]:
        """Fetch DEX data for memecoin / new token analysis."""
        try:
            url = f"https://api.dexscreener.com/latest/dex/pair/{chain}/{pair}"
            data = requests.get(url, timeout=5).json()
            pair_data = data.get("pair", {})
            return {
                "price": float(pair_data.get("priceUsd", 0)),
                "liquidity": float(pair_data.get("liquidity", {}).get("usd", 0)),
                "volume_24h": float(pair_data.get("volume", {}).get("h24", 0)),
                "fdv": float(pair_data.get("fdv", 0)),
            }
        except: return None

    def get_price(self, symbol: str, source: str = "coingecko") -> Optional[float]:
        fetcher = self.sources.get(source)
        if fetcher:
            return fetcher(symbol)
        return None

    def get_prices(self, symbols: List[str]) -> Dict[str, float]:
        return {s: self.get_price(s) for s in symbols if self.get_price(s)}
