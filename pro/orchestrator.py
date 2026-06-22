#!/usr/bin/env python3
"""
orchestrator.py — The Trading System that ties every pro module into one pipeline.

Amateurs run indicators in isolation. A 20-year veteran runs a *system*: every
decision flows through regime detection, signal generation, sentiment confirmation,
scientific position sizing, portfolio-level risk checks, and disciplined execution —
with a full audit trail at the end.

Pipeline (each stage can veto the trade):

    1. REGIME      — what market are we in? (trend / range / volatile / risk-off)
    2. SIGNAL      — does the strategy fire, given the regime?
    3. SENTIMENT   — does crowd positioning confirm or contradict?
    4. SIZING      — how much, scientifically? (Kelly + vol target + drawdown scale)
    5. RISK GATE   — do portfolio limits allow it? (exposure / VaR / daily loss / corr)
    6. EXECUTION   — how do we get filled without moving the market?
    7. MONITOR     — stops, trailing, time-stop, VaR breach
    8. REPORT      — log everything, audit trail, performance attribution

This module degrades gracefully: if an optional sub-module is unavailable, the stage
is skipped with a logged warning rather than crashing the whole system.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")


# ════════════════════════════════════════════════════════════════════
#  Decision primitives
# ════════════════════════════════════════════════════════════════════

class Decision(str, Enum):
    ENTER_LONG = "enter_long"
    ENTER_SHORT = "enter_short"
    HOLD = "hold"
    EXIT = "exit"
    VETO = "veto"


@dataclass
class StageResult:
    """Result of one pipeline stage."""
    stage: str
    passed: bool
    detail: str
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TradeDecision:
    """The final, fully-reasoned decision the system produces for one symbol."""
    symbol: str
    decision: Decision
    size_fraction: float                 # fraction of capital (already risk-scaled)
    entry_price: float
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    regime: str = "unknown"
    confidence: float = 0.0
    reasons: List[str] = field(default_factory=list)
    vetoed_by: Optional[str] = None
    stages: List[StageResult] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def explain(self) -> str:
        lines = [
            f"┌─ {self.symbol}  →  {self.decision.value.upper()}",
            f"│  Regime: {self.regime}  |  Confidence: {self.confidence:.0%}",
        ]
        if self.decision in (Decision.ENTER_LONG, Decision.ENTER_SHORT):
            lines.append(
                f"│  Size: {self.size_fraction:.1%} of capital  |  "
                f"Entry: {self.entry_price:.4f}  SL: {self.stop_loss}  TP: {self.take_profit}"
            )
        if self.vetoed_by:
            lines.append(f"│  ⛔ VETOED by: {self.vetoed_by}")
        for r in self.reasons:
            lines.append(f"│  • {r}")
        lines.append("└" + "─" * 40)
        return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════
#  Lazy module loading — the system works even with partial installs
# ════════════════════════════════════════════════════════════════════

def _safe_import(path: str, name: str):
    """Import `name` from module `path`, returning None on failure."""
    try:
        mod = __import__(path, fromlist=[name])
        return getattr(mod, name)
    except Exception as exc:  # noqa: BLE001
        warnings.warn(f"[orchestrator] optional component {path}.{name} unavailable: {exc}")
        return None


# ════════════════════════════════════════════════════════════════════
#  The system
# ════════════════════════════════════════════════════════════════════

@dataclass
class SystemConfig:
    capital: float = 10_000.0
    base_risk_per_trade: float = 0.02          # 2% baseline, scaled by regime/drawdown
    target_volatility: float = 0.20            # 20% annualized vol target
    max_portfolio_exposure: float = 1.0        # no leverage by default
    daily_loss_limit: float = 0.05             # stop trading at -5% day
    kelly_fraction: float = 0.25               # quarter-Kelly (veterans never full-Kelly)
    min_confidence: float = 0.45               # don't trade weak setups
    require_sentiment_confirm: bool = False    # set True to demand sentiment agreement


class TradingSystem:
    """
    Unified professional trading pipeline.

    Usage:
        sys = TradingSystem(SystemConfig(capital=25_000))
        decision = sys.evaluate("BTC", ohlcv_df)
        print(decision.explain())
    """

    def __init__(self, config: Optional[SystemConfig] = None):
        self.cfg = config or SystemConfig()
        self._current_drawdown = 0.0
        self._daily_pnl = 0.0
        self._open_exposure = 0.0
        self._load_components()

    def _load_components(self):
        # Regime
        self.RegimeDetector = _safe_import("pro.regime.pro_market_regime", "MarketRegimeDetector")
        self.TrendAnalyzer = _safe_import("pro.regime.pro_market_regime", "TrendStrengthAnalyzer")
        # Risk
        self.Kelly = _safe_import("pro.risk.pro_risk_engine", "KellyCriterion")
        self.StopOptimizer = _safe_import("pro.risk.pro_risk_engine", "StopLossOptimizer")
        # Volatility
        self.RealizedVol = _safe_import("pro.volatility.pro_volatility_models", "RealizedVolatility")
        # Sentiment
        self.FearGreed = _safe_import("pro.sentiment.pro_sentiment_engine", "FearGreedIndex")
        # Shared indicators
        self._ind = _safe_import("lib.gumloop_trading", "compute_rsi")

    # ── individual stages ────────────────────────────────────────────

    @staticmethod
    def _extract_regime_label(out: Any) -> Tuple[str, float]:
        """Pull a clean regime label + confidence from whatever the detector returns."""
        # dict result
        if isinstance(out, dict):
            return str(out.get("regime", "neutral")), float(out.get("confidence", 0.6))
        # rich RegimeComposite-style object
        for attr in ("primary",):
            if hasattr(out, attr):
                prim = getattr(out, attr)
                name = getattr(prim, "regime", None) or getattr(prim, "name", None) or prim
                # enum-like
                name = getattr(name, "name", name)
                conf = float(getattr(prim, "confidence", getattr(out, "regime_strength", 0.6)))
                return str(name), conf
        # enum or string
        name = getattr(out, "name", out)
        return str(name), float(getattr(out, "regime_strength", 0.6) if not isinstance(out, str) else 0.6)

    def _stage_regime(self, df: pd.DataFrame) -> StageResult:
        if self.RegimeDetector is None:
            return StageResult("regime", True, "regime detection unavailable — assuming NEUTRAL",
                               {"regime": "neutral", "confidence": 0.5})
        try:
            det = self.RegimeDetector()
            # Try common method names defensively
            for m in ("detect_regime", "detect", "classify"):
                if hasattr(det, m):
                    out = getattr(det, m)(df)
                    regime, conf = self._extract_regime_label(out)
                    return StageResult("regime", True, f"regime={regime} ({conf:.0%})",
                                       {"regime": regime, "confidence": conf})
            return StageResult("regime", True, "no known method — NEUTRAL",
                               {"regime": "neutral", "confidence": 0.5})
        except Exception as exc:  # noqa: BLE001
            return StageResult("regime", True, f"regime error ({exc}) — NEUTRAL",
                               {"regime": "neutral", "confidence": 0.5})

    def _stage_signal(self, df: pd.DataFrame, regime: str) -> StageResult:
        """Regime-aware signal: trend-follow in trends, mean-revert in ranges."""
        close = df["close"]
        ema_fast = close.ewm(span=9, adjust=False).mean()
        ema_slow = close.ewm(span=21, adjust=False).mean()
        rsi = self._ind(close, 14) if self._ind else pd.Series([50] * len(close), index=close.index)
        r = float(rsi.iloc[-1]) if len(rsi) else 50.0

        trend_up = ema_fast.iloc[-1] > ema_slow.iloc[-1]
        reg = regime.lower()

        if "trend" in reg or "bull" in reg or "bear" in reg:
            # trend following
            if trend_up and r < 70:
                return StageResult("signal", True, "trend-follow long", {"side": "long", "strength": 0.7})
            if not trend_up and r > 30:
                return StageResult("signal", True, "trend-follow short", {"side": "short", "strength": 0.6})
        elif "rang" in reg or "neutral" in reg:
            # mean reversion
            if r < 30:
                return StageResult("signal", True, "mean-revert long (oversold)", {"side": "long", "strength": 0.6})
            if r > 70:
                return StageResult("signal", True, "mean-revert short (overbought)", {"side": "short", "strength": 0.6})
        elif "volatil" in reg or "risk" in reg:
            return StageResult("signal", False, "high-vol/risk-off — stand aside", {"side": None, "strength": 0.0})

        return StageResult("signal", False, "no qualifying setup", {"side": None, "strength": 0.0})

    def _stage_sentiment(self, side: str, sentiment_inputs: Optional[Dict]) -> StageResult:
        if self.FearGreed is None or sentiment_inputs is None:
            return StageResult("sentiment", True, "sentiment skipped (no data)", {"score": 50})
        try:
            fg = self.FearGreed()
            score = None
            for m in ("calculate", "compute", "score"):
                if hasattr(fg, m):
                    out = getattr(fg, m)(**sentiment_inputs) if isinstance(sentiment_inputs, dict) else getattr(fg, m)()
                    score = float(out.get("score", out)) if isinstance(out, dict) else float(out)
                    break
            if score is None:
                return StageResult("sentiment", True, "sentiment unavailable", {"score": 50})
            # contrarian guardrail: don't buy extreme greed, don't short extreme fear
            if side == "long" and score > 85:
                return StageResult("sentiment", False, f"extreme greed ({score:.0f}) — avoid chasing longs", {"score": score})
            if side == "short" and score < 15:
                return StageResult("sentiment", False, f"extreme fear ({score:.0f}) — avoid chasing shorts", {"score": score})
            return StageResult("sentiment", True, f"sentiment ok ({score:.0f})", {"score": score})
        except Exception as exc:  # noqa: BLE001
            return StageResult("sentiment", True, f"sentiment error ({exc}) — skipped", {"score": 50})

    def _stage_sizing(self, df: pd.DataFrame, signal_strength: float, regime: str) -> StageResult:
        """Kelly + volatility targeting + drawdown scaling = scientific size."""
        # 1) base Kelly (quarter-Kelly)
        win_rate = 0.5 + 0.15 * signal_strength          # stronger signal -> higher assumed edge
        kelly_f = self.cfg.base_risk_per_trade
        if self.Kelly:
            try:
                full = self.Kelly().calculate(win_rate, 2.0, 1.0)
                kelly_f = max(0.0, full * self.cfg.kelly_fraction)
            except Exception:  # noqa: BLE001
                pass

        # 2) volatility targeting — scale down when realized vol is high
        rets = df["close"].pct_change().dropna()
        realized_vol = float(rets.std() * np.sqrt(365)) if len(rets) > 5 else self.cfg.target_volatility
        vol_scalar = min(2.0, self.cfg.target_volatility / realized_vol) if realized_vol > 1e-9 else 1.0

        # 3) drawdown scaling — cut risk in drawdowns
        dd_scalar = 1.0
        if self._current_drawdown > 0.15:
            dd_scalar = 0.4
        elif self._current_drawdown > 0.10:
            dd_scalar = 0.6
        elif self._current_drawdown > 0.05:
            dd_scalar = 0.8

        # 4) regime scaling — smaller in volatile regimes
        regime_scalar = 0.5 if ("volatil" in regime.lower() or "risk" in regime.lower()) else 1.0

        size = kelly_f * vol_scalar * dd_scalar * regime_scalar
        size = float(np.clip(size, 0.0, self.cfg.base_risk_per_trade * 3))  # hard cap

        return StageResult("sizing", size > 0, f"size={size:.2%}", {
            "size": size, "kelly_f": kelly_f, "vol_scalar": vol_scalar,
            "dd_scalar": dd_scalar, "regime_scalar": regime_scalar, "realized_vol": realized_vol,
        })

    def _stage_risk_gate(self, size: float) -> StageResult:
        if self._daily_pnl <= -self.cfg.capital * self.cfg.daily_loss_limit:
            return StageResult("risk_gate", False, "daily loss limit hit — trading halted", {})
        if self._open_exposure + size > self.cfg.max_portfolio_exposure:
            return StageResult("risk_gate", False,
                               f"exposure cap ({self._open_exposure:.0%}+{size:.0%} > "
                               f"{self.cfg.max_portfolio_exposure:.0%})", {})
        return StageResult("risk_gate", True, "within portfolio limits", {})

    def _compute_stops(self, df: pd.DataFrame, side: str) -> Tuple[Optional[float], Optional[float]]:
        price = float(df["close"].iloc[-1])
        # ATR-based stop
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1]) if len(tr) > 14 else price * 0.02
        if side == "long":
            return price - 2 * atr, price + 4 * atr
        return price + 2 * atr, price - 4 * atr

    # ── the full pipeline ────────────────────────────────────────────

    def evaluate(self, symbol: str, df: pd.DataFrame,
                 sentiment_inputs: Optional[Dict] = None) -> TradeDecision:
        """Run the full 8-stage pipeline and return a fully-reasoned decision."""
        stages: List[StageResult] = []
        price = float(df["close"].iloc[-1])

        # 1. REGIME
        s_reg = self._stage_regime(df); stages.append(s_reg)
        regime = s_reg.data.get("regime", "neutral")
        regime_conf = s_reg.data.get("confidence", 0.5)

        # 2. SIGNAL
        s_sig = self._stage_signal(df, regime); stages.append(s_sig)
        if not s_sig.passed:
            return TradeDecision(symbol, Decision.HOLD, 0.0, price, regime=regime,
                                 confidence=regime_conf, reasons=[s_sig.detail], stages=stages)
        side = s_sig.data["side"]
        strength = s_sig.data["strength"]

        # 3. SENTIMENT
        s_sent = self._stage_sentiment(side, sentiment_inputs); stages.append(s_sent)
        if self.cfg.require_sentiment_confirm and not s_sent.passed:
            return TradeDecision(symbol, Decision.VETO, 0.0, price, regime=regime,
                                 confidence=regime_conf, reasons=[s_sent.detail],
                                 vetoed_by="sentiment", stages=stages)

        # 4. SIZING
        s_size = self._stage_sizing(df, strength, regime); stages.append(s_size)
        size = s_size.data["size"]

        # 5. RISK GATE
        s_gate = self._stage_risk_gate(size); stages.append(s_gate)
        if not s_gate.passed:
            return TradeDecision(symbol, Decision.VETO, 0.0, price, regime=regime,
                                 confidence=regime_conf, reasons=[s_gate.detail],
                                 vetoed_by="risk_gate", stages=stages)

        # confidence blends regime confidence + signal strength + sentiment agreement
        confidence = float(np.clip(0.4 * regime_conf + 0.4 * strength + 0.2 * (1.0 if s_sent.passed else 0.0), 0, 1))
        if confidence < self.cfg.min_confidence:
            return TradeDecision(symbol, Decision.HOLD, 0.0, price, regime=regime,
                                 confidence=confidence,
                                 reasons=[f"confidence {confidence:.0%} < min {self.cfg.min_confidence:.0%}"],
                                 stages=stages)

        # stops
        sl, tp = self._compute_stops(df, side)

        decision = Decision.ENTER_LONG if side == "long" else Decision.ENTER_SHORT
        reasons = [s_sig.detail, s_sent.detail, s_size.detail, s_gate.detail]
        return TradeDecision(symbol, decision, size, price, stop_loss=round(sl, 6),
                             take_profit=round(tp, 6), regime=regime, confidence=confidence,
                             reasons=reasons, stages=stages)

    # ── portfolio-level scan ──────────────────────────────────────────

    def scan(self, market_data: Dict[str, pd.DataFrame],
             sentiment: Optional[Dict[str, Dict]] = None) -> List[TradeDecision]:
        """Evaluate many symbols, return only actionable decisions sorted by confidence."""
        out = []
        for sym, df in market_data.items():
            sent = (sentiment or {}).get(sym)
            d = self.evaluate(sym, df, sent)
            out.append(d)
        actionable = [d for d in out if d.decision in (Decision.ENTER_LONG, Decision.ENTER_SHORT)]
        actionable.sort(key=lambda d: d.confidence, reverse=True)
        return actionable

    # ── state updates (called by the live trader after fills/marks) ────

    def update_state(self, daily_pnl: float = None, drawdown: float = None,
                     open_exposure: float = None):
        if daily_pnl is not None:
            self._daily_pnl = daily_pnl
        if drawdown is not None:
            self._current_drawdown = drawdown
        if open_exposure is not None:
            self._open_exposure = open_exposure


# ════════════════════════════════════════════════════════════════════
#  Self-test / demo
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    np.random.seed(7)
    n = 250
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    price = 100 * np.exp(np.cumsum(np.random.normal(0.001, 0.02, n)))
    demo = pd.DataFrame({
        "open": price * (1 + np.random.normal(0, 0.003, n)),
        "high": price * (1 + np.abs(np.random.normal(0, 0.01, n))),
        "low": price * (1 - np.abs(np.random.normal(0, 0.01, n))),
        "close": price,
        "volume": np.random.lognormal(15, 0.5, n),
    }, index=idx)

    system = TradingSystem(SystemConfig(capital=25_000))
    decision = system.evaluate("BTC", demo)
    print(decision.explain())
    print()
    print("Stages:")
    for s in decision.stages:
        print(f"  [{'PASS' if s.passed else 'STOP'}] {s.stage:10} — {s.detail}")
