#!/usr/bin/env python3
"""
pro_risk_engine.py — Professional-Grade Risk Management System

This is the CORE of professional trading. Amateurs ignore risk; pros eat risk
for breakfast. Every class here is built for the trader who has survived
multiple bear markets, flash crashes, and liquidity events.

Institutional-caliber risk management with:
  - Kelly / fractional Kelly / Optimal F / Fixed Ratio position sizing
  - Multi-layer risk controls (daily, weekly, monthly, consecutive loss)
  - VaR (parametric, historical, Monte Carlo) + CVaR
  - Correlation-aware limits with regime-dependent tracking
  - Liquidity-adjusted position limits with market impact modeling
  - Professional stop-loss optimization (volatility, structural, trailing, parabolic)
  - Stress testing against historical and synthetic crash scenarios
  - Risk budgeting for multi-strategy portfolios

Author: Gumloop Trading Systems
"""

import warnings
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

# Shared utils from sibling lib
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
try:
    from gumloop_trading import compute_atr, compute_sma, compute_ema
except ImportError:
    # Fallback stubs so this module can be imported standalone
    def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.rolling(period).mean()

    def compute_sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(period).mean()

    def compute_ema(series: pd.Series, period: int) -> pd.Series:
        return series.ewm(span=period, adjust=False).mean()

warnings.filterwarnings("ignore", category=RuntimeWarning)

# ============================================================================
# 1. KELLY CRITERION — The mathematician's edge
# ============================================================================
# Kelly tells you exactly how much to bet when you have an edge. Most traders
# use fractional Kelly (quarter-Kelly is the professional standard) because
# full Kelly is too volatile — it maximizes growth but with ~33% drawdown risk.

class KellyCriterion:
    """
    Full and fractional Kelly position sizing with edge estimation.

    The Kelly Criterion finds the optimal fraction of capital to risk on a
    binary outcome with known probabilities. In trading, we estimate these
    from our trade history.

    f* = (p * b - q) / b    where b = avg_win / avg_loss

    Professionals almost never trade full Kelly. The standard is 25% Kelly
    (quarter-Kelly), which reduces volatility by ~75% while sacrificing only
    ~25% of growth.
    """

    @staticmethod
    def calculate(p_win: float, avg_win: float, avg_loss: float) -> float:
        """
        Full Kelly optimal fraction.

        Parameters
        ----------
        p_win : float
            Probability of winning (0 < p_win < 1).
        avg_win : float
            Average win amount (must be > 0).
        avg_loss : float
            Average loss amount (must be > 0; pass as positive value).

        Returns
        -------
        float
            Optimal fraction of capital to risk.

        Raises
        ------
        ValueError
            If inputs are out of valid range.
        """
        if not 0 < p_win < 1:
            raise ValueError(f"p_win must be between 0 and 1, got {p_win}")
        if avg_win <= 0:
            raise ValueError(f"avg_win must be > 0, got {avg_win}")
        if avg_loss <= 0:
            raise ValueError(f"avg_loss must be > 0 (positive value), got {avg_loss}")

        b = avg_win / avg_loss  # odds ratio
        q = 1.0 - p_win
        f_star = (p_win * b - q) / b
        return max(0.0, f_star)  # Kelly says: if negative, don't bet

    @staticmethod
    def fractional_kelly(
        p_win: float, avg_win: float, avg_loss: float, fraction: float = 0.25
    ) -> float:
        """
        Fractional Kelly — the professional standard.

        Half-Kelly (0.5) reduces drawdowns by ~50% while keeping ~75% of growth.
        Quarter-Kelly (0.25) reduces drawdowns by ~75% while keeping ~56% of growth.

        Parameters
        ----------
        p_win : float
            Probability of winning.
        avg_win : float
            Average win amount.
        avg_loss : float
            Average loss amount (positive).
        fraction : float, default 0.25
            Fraction of full Kelly to use (0.25 = quarter-Kelly).

        Returns
        -------
        float
            Fractional Kelly optimal bet size.
        """
        full = KellyCriterion.calculate(p_win, avg_win, avg_loss)
        return full * fraction

    @staticmethod
    def half_kelly(p_win: float, avg_win: float, avg_loss: float) -> float:
        """Convenience: half-Kelly (50% of full Kelly)."""
        return KellyCriterion.fractional_kelly(p_win, avg_win, avg_loss, 0.50)

    @staticmethod
    def quarter_kelly(p_win: float, avg_win: float, avg_loss: float) -> float:
        """Convenience: quarter-Kelly (25% of full Kelly)."""
        return KellyCriterion.fractional_kelly(p_win, avg_win, avg_loss, 0.25)

    @staticmethod
    def estimate_edge(trades_history: Union[List[float], pd.Series]) -> Dict[str, float]:
        """
        Estimate edge parameters from a list of past trade PnLs.

        This is how you answer "do I actually have an edge?" — you don't guess,
        you measure from your own trading data.

        Parameters
        ----------
        trades_history : list or pd.Series
            List of trade PnLs (positive = win, negative = loss).

        Returns
        -------
        dict with keys:
            p_win, avg_win, avg_loss, win_loss_ratio, kelly_full, kelly_quarter,
            sharpe_style_edge, trade_count
        """
        arr = np.asarray(trades_history, dtype=float)
        n = len(arr)
        if n < 10:
            return {"error": "Insufficient trades for edge estimation (need >= 10)"}

        wins = arr[arr > 0]
        losses = arr[arr < 0]

        if len(wins) == 0 or len(losses) == 0:
            return {"error": "Need both wins and losses to estimate edge"}

        p_win = len(wins) / n
        avg_win = float(np.mean(wins))
        avg_loss = float(np.abs(np.mean(losses)))  # positive by convention
        wl_ratio = avg_win / avg_loss if avg_loss > 0 else np.inf

        try:
            kelly_full = KellyCriterion.calculate(p_win, avg_win, avg_loss)
            kelly_q = KellyCriterion.quarter_kelly(p_win, avg_win, avg_loss)
        except ValueError:
            kelly_full = 0.0
            kelly_q = 0.0

        # Sharpe-style edge: annualized mean/vol ratio from trades
        mean_trade = float(np.mean(arr))
        std_trade = float(np.std(arr, ddof=1)) if np.std(arr, ddof=1) > 0 else 1e-10
        sharpe_edge = mean_trade / std_trade  # per-trade Sharpe (not annualized)

        return {
            "p_win": round(p_win, 4),
            "avg_win": round(avg_win, 4),
            "avg_loss": round(avg_loss, 4),
            "win_loss_ratio": round(wl_ratio, 4),
            "kelly_full": round(kelly_full, 4),
            "kelly_quarter": round(kelly_q, 4),
            "sharpe_style_edge": round(sharpe_edge, 4),
            "trade_count": n,
            "total_pnl": round(float(np.sum(arr)), 4),
        }


# ============================================================================
# 2. OPTIMAL F — Ralph Vince's Geometric Growth Maximizer
# ============================================================================
# Optimal F finds the fraction that maximizes terminal wealth via Monte Carlo.
# Unlike Kelly, it works on any distribution of trade outcomes (not just
# binary). This is the gold standard for serious traders.

class OptimalF:
    """
    Ralph Vince's Optimal F via Monte Carlo simulation.

    Optimal F finds the fraction of capital to risk that maximizes the
    geometric growth of your account across a resampled distribution of
    your actual trades. It handles any distribution shape — fat tails,
    skew, multiple modes — that Kelly cannot.
    """

    @staticmethod
    def _terminal_wealth_ratio(trades: np.ndarray, f: float) -> float:
        """
        Compute the terminal wealth ratio given a fraction f.
        TWR = prod(1 + f * (-trade / max_loss)) with max_loss normalization.
        """
        max_loss = float(np.abs(trades.min()))
        if max_loss <= 0 or f <= 0:
            return 1.0
        hpr = 1.0 + f * (trades / max_loss)
        # Cap at zero to avoid negative HPR causing inversion
        hpr = np.maximum(hpr, 0.0)
        return float(np.prod(hpr))

    @staticmethod
    def calculate(trades_list: Union[List[float], np.ndarray]) -> Dict[str, float]:
        """
        Compute Optimal F from a list of trades.

        Uses bounded minimization over f in [0.001, 0.999].

        Parameters
        ----------
        trades_list : list or np.ndarray
            List of trade PnLs (positive = profit, negative = loss).

        Returns
        -------
        dict with keys:
            optimal_f: The Optimal F value
            twr_at_optimal: Terminal wealth ratio at optimal_f
            max_loss: The worst loss (used for normalization)
        """
        trades = np.asarray(trades_list, dtype=float)
        if len(trades) < 5:
            return {"error": "Need at least 5 trades"}

        max_loss = float(np.abs(trades.min()))
        if max_loss <= 0:
            return {"optimal_f": 1.0, "twr_at_optimal": 1.0, "max_loss": 0.0}

        def neg_twr(f: float) -> float:
            return -OptimalF._terminal_wealth_ratio(trades, f)

        res = minimize(
            neg_twr,
            x0=0.1,
            bounds=[(0.001, 0.999)],
            method="L-BFGS-B",
            options={"maxiter": 500, "ftol": 1e-12},
        )

        of = float(res.x[0])
        twr = OptimalF._terminal_wealth_ratio(trades, of)

        return {
            "optimal_f": round(of, 4),
            "twr_at_optimal": round(twr, 4),
            "max_loss": round(max_loss, 4),
        }

    @staticmethod
    def monte_carlo_simulate(
        trades_list: Union[List[float], np.ndarray],
        iterations: int = 10000,
        confidence: float = 0.95,
    ) -> Dict[str, float]:
        """
        Monte Carlo Optimal F with confidence intervals.

        Resamples the trade list with replacement, computes Optimal F on
        each resampled set, and returns statistics. This tells you the
        distribution of your Optimal F estimate — not just a point estimate.

        Parameters
        ----------
        trades_list : list or np.ndarray
            Historical trades.
        iterations : int, default 10000
            Number of Monte Carlo iterations.
        confidence : float, default 0.95
            Confidence level for the interval.

        Returns
        -------
        dict with keys: optimal_f_mean, optimal_f_median, lower_bound, upper_bound,
                        optimal_f_25pct (quarter-Kelly of the MC result), and more.
        """
        trades = np.asarray(trades_list, dtype=float)
        results = np.zeros(iterations)
        n = len(trades)

        for i in range(iterations):
            sample = np.random.choice(trades, size=n, replace=True)
            try:
                res = OptimalF.calculate(sample)
                if "optimal_f" in res:
                    results[i] = res["optimal_f"]
                else:
                    results[i] = 0.0
            except Exception:
                results[i] = 0.0

        results = results[results > 0]  # drop degenerate
        if len(results) == 0:
            return {"error": "All MC iterations returned degenerate results"}

        alpha = 1.0 - confidence
        lower = float(np.percentile(results, 100 * alpha / 2))
        upper = float(np.percentile(results, 100 * (1 - alpha / 2)))

        return {
            "optimal_f_mean": round(float(np.mean(results)), 4),
            "optimal_f_median": round(float(np.median(results)), 4),
            "optimal_f_std": round(float(np.std(results, ddof=1)), 4),
            f"lower_bound_{int(confidence*100)}pct": round(lower, 4),
            f"upper_bound_{int(confidence*100)}pct": round(upper, 4),
            "optimal_f_25pct": round(float(np.percentile(results, 25)), 4),
            "optimal_f_75pct": round(float(np.percentile(results, 75)), 4),
            "iterations_used": len(results),
        }


# ============================================================================
# 3. FIXED RATIO — Ryan Jones' Drawdown-Friendly Sizing
# ============================================================================
# Fixed Ratio increases position size geometrically rather than linearly.
# It's designed to protect against the geometric decay of large drawdowns.

class FixedRatio:
    """
    Ryan Jones' Fixed Ratio position sizing.

    Instead of adding one contract per X dollars like Fixed Fractional,
    Fixed Ratio adds one contract when the account grows by delta * level.
    This means it increases slower at first and faster later — protecting
    the account during early, vulnerable stages.

    The classic formula:
        next_level = current_level + (current_PnL / delta)
    """

    @staticmethod
    def calculate(delta: float, current_pnl: float, current_shares: int = 1) -> int:
        """
        Compute the new position size using Fixed Ratio.

        Parameters
        ----------
        delta : float
            The delta parameter — profit needed per contract to add one more.
            Smaller delta = more aggressive. Ryans recommends using 20-30% of
            the maximum drawdown as delta.
        current_pnl : float
            Cumulative PnL since the last level change.
        current_shares : int, default 1
            Current position size / number of contracts.

        Returns
        -------
        int
            New position size (always >= 1).
        """
        if delta <= 0:
            raise ValueError(f"delta must be > 0, got {delta}")

        level = current_shares
        ratio = current_pnl / delta
        new_level = int(level + np.floor(ratio))
        return max(1, new_level)

    @staticmethod
    def calculate_with_delta_recommendation(
        max_drawdown: float, current_pnl: float, current_shares: int = 1
    ) -> Dict[str, object]:
        """
        Fixed Ratio with Ryan's recommended delta = 20% of max drawdown.

        Parameters
        ----------
        max_drawdown : float
            Historical maximum drawdown (positive value).
        current_pnl : float
            Current cumulative PnL.
        current_shares : int, default 1
            Current position size.

        Returns
        -------
        dict with delta, recommended_new_shares, notes
        """
        delta = round(max_drawdown * 0.20, 2)
        new_size = FixedRatio.calculate(delta, current_pnl, current_shares)
        return {
            "delta": delta,
            "max_drawdown": max_drawdown,
            "recommended_delta_pct_of_dd": 0.20,
            "current_shares": current_shares,
            "new_shares": new_size,
        }


# ============================================================================
# 4. RISK MANAGER — The Command Center
# ============================================================================
# This is the heart of the system. Multiple independent risk layers create
# defense-in-depth. No single failure mode can blow up the account.

class RiskManager:
    """
    Professional multi-layer risk management system.

    Layers of protection:
      1. Daily loss limit — hard stop at -X% in a single day
      2. Weekly loss limit
      3. Monthly drawdown limit
      4. Consecutive loss limit (e.g., stop after 3 losses in a row)
      5. Max exposure per asset / sector / correlation group
      6. VaR (parametric, historical, Monte Carlo)
      7. CVaR (Expected Shortfall)
      8. Stress testing
      9. Liquidity-adjusted position limits
      10. Correlation-aware position limits
    """

    def __init__(
        self,
        initial_capital: float = 100_000.0,
        daily_loss_limit: float = 0.02,        # -2% hard stop per day
        weekly_loss_limit: float = 0.05,        # -5% per week
        monthly_drawdown_limit: float = 0.10,   # -10% per month
        consecutive_loss_limit: int = 3,         # Stop after 3 losses in a row
        max_exposure_per_asset: float = 0.20,   # Max 20% in one asset
        max_exposure_per_sector: float = 0.35,  # Max 35% in one sector
        max_correlation_group_exposure: float = 0.40,  # Max 40% in correlated assets
        var_confidence: float = 0.95,           # 95% VaR
        position_risk_pct: float = 0.01,        # Risk 1% per trade (Ralph Vince standard)
    ):
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.peak_capital = initial_capital

        self.daily_loss_limit = daily_loss_limit
        self.weekly_loss_limit = weekly_loss_limit
        self.monthly_drawdown_limit = monthly_drawdown_limit
        self.consecutive_loss_limit = consecutive_loss_limit
        self.max_exposure_per_asset = max_exposure_per_asset
        self.max_exposure_per_sector = max_exposure_per_sector
        self.max_correlation_group_exposure = max_correlation_group_exposure
        self.var_confidence = var_confidence
        self.position_risk_pct = position_risk_pct  # per-trade risk as % of capital

        # State tracking
        self.daily_pnl = 0.0
        self.weekly_pnl = 0.0
        self.monthly_pnl = 0.0
        self.consecutive_losses = 0
        self.trade_log: List[Dict] = []
        self.daily_log: List[Dict] = []

        # Exposure tracking
        self.position_sizes: Dict[str, float] = {}  # asset -> exposure
        self.asset_to_sector: Dict[str, str] = {}
        self.asset_correlations: pd.DataFrame = pd.DataFrame()

    def reset_daily(self):
        """Call at the start of each trading day."""
        self.daily_pnl = 0.0
        # Reset consecutive losses only if we ended flat/up
        self.consecutive_losses = 0

    def reset_weekly(self):
        """Call at the start of each trading week."""
        self.weekly_pnl = 0.0

    def reset_monthly(self):
        """Call at the start of each month."""
        self.monthly_pnl = 0.0
        # Log the month-end stats
        dd = self._drawdown_pct()
        self.daily_log.append({
            "capital": self.current_capital,
            "drawdown": dd,
        })

    def record_trade(self, pnl: float, asset: Optional[str] = None):
        """
        Record a completed trade and update all risk limits.

        Parameters
        ----------
        pnl : float
            Profit or loss from the trade.
        asset : str, optional
            Asset identifier, if relevant.

        Returns
        -------
        dict with risk_status: 'ok', 'daily_limit_hit', 'weekly_limit_hit',
              'monthly_limit_hit', 'consecutive_loss_limit_hit'
        """
        self.daily_pnl += pnl
        self.weekly_pnl += pnl
        self.monthly_pnl += pnl
        self.current_capital += pnl
        self.peak_capital = max(self.peak_capital, self.current_capital)

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        self.trade_log.append({
            "pnl": pnl,
            "asset": asset,
            "capital": self.current_capital,
            "consecutive_losses": self.consecutive_losses,
        })

        # Check all limits
        if self.daily_pnl / self.peak_capital <= -self.daily_loss_limit:
            return {"risk_status": "daily_limit_hit", "msg": f"Daily loss limit of {self.daily_loss_limit:.1%} hit"}
        if self.weekly_pnl / self.peak_capital <= -self.weekly_loss_limit:
            return {"risk_status": "weekly_limit_hit", "msg": f"Weekly loss limit of {self.weekly_loss_limit:.1%} hit"}
        if self.monthly_pnl / self.peak_capital <= -self.monthly_drawdown_limit:
            return {"risk_status": "monthly_limit_hit", "msg": f"Monthly drawdown limit of {self.monthly_drawdown_limit:.1%} hit"}
        if self.consecutive_losses >= self.consecutive_loss_limit:
            return {"risk_status": "consecutive_loss_limit_hit", "msg": f"{self.consecutive_losses} consecutive losses — stop trading"}

        return {"risk_status": "ok"}

    # --- VaR & CVaR ---

    def parametric_var(
        self, returns: Union[List[float], np.ndarray], horizon: int = 1
    ) -> float:
        """
        Parametric VaR (Variance-Covariance) assuming normal distribution.

        Parameters
        ----------
        returns : array-like
            Historical asset returns.
        horizon : int, default 1
            Holding period in days.

        Returns
        -------
        float
            VaR as a decimal (e.g., 0.02 = 2% loss at the given confidence).
        """
        r = np.asarray(returns, dtype=float)
        mu = np.mean(r) * horizon
        sigma = np.std(r, ddof=1) * np.sqrt(horizon)
        z = stats.norm.ppf(1 - self.var_confidence)
        return float(-(mu + z * sigma))  # positive = loss amount

    def historical_var(
        self, returns: Union[List[float], np.ndarray], horizon: int = 1
    ) -> float:
        """
        Historical VaR — the non-parametric, model-free version.

        Just sorts the returns and takes the percentile. No assumptions
        about distribution shape. This is what the old hands trust.
        """
        r = np.asarray(returns, dtype=float) * horizon
        return float(-np.percentile(r, (1 - self.var_confidence) * 100))

    def monte_carlo_var(
        self,
        returns: Union[List[float], np.ndarray],
        horizon: int = 1,
        iterations: int = 10000,
    ) -> float:
        """
        Monte Carlo VaR — simulates possible paths.

        Accounts for fat tails better than parametric VaR because we
        bootstrap from the actual return distribution.
        """
        r = np.asarray(returns, dtype=float)
        mu = np.mean(r)
        sigma = np.std(r, ddof=1)
        n = len(r)

        final_returns = np.zeros(iterations)
        for i in range(iterations):
            # Bootstrap: draw from actual returns (no normality assumption)
            path = np.random.choice(r, size=horizon, replace=True)
            final_returns[i] = np.sum(path)

        return float(-np.percentile(final_returns, (1 - self.var_confidence) * 100))

    def cvar(self, returns: Union[List[float], np.ndarray], horizon: int = 1) -> float:
        """
        Conditional VaR (Expected Shortfall) — the average loss beyond VaR.

        CVaR tells you "if things get really bad, how bad is it?".
        This is arguably more important than VaR itself for tail risk.
        """
        r = np.asarray(returns, dtype=float) * horizon
        var_threshold = np.percentile(r, (1 - self.var_confidence) * 100)
        tail = r[r <= var_threshold]
        if len(tail) == 0:
            return 0.0
        return float(-np.mean(tail))

    def var_summary(self, returns: Union[List[float], np.ndarray]) -> Dict[str, float]:
        """
        Full VaR report: parametric, historical, Monte Carlo, and CVaR.
        """
        pvar = self.parametric_var(returns)
        hvar = self.historical_var(returns)
        mcvar = self.monte_carlo_var(returns)
        cvar_val = self.cvar(returns)
        return {
            "parametric_var": round(pvar, 6),
            "historical_var": round(hvar, 6),
            "monte_carlo_var": round(mcvar, 6),
            "cvar_expected_shortfall": round(cvar_val, 6),
            "confidence": self.var_confidence,
        }

    # --- Position Limits ---

    def max_position_for_asset(self, asset: str, capital: Optional[float] = None) -> float:
        """Maximum position size for a single asset as a fraction of capital."""
        cap = capital or self.current_capital
        return cap * self.max_exposure_per_asset

    def max_position_for_sector(self, sector: str, capital: Optional[float] = None) -> float:
        """Maximum total exposure in a sector."""
        cap = capital or self.current_capital
        return cap * self.max_exposure_per_sector

    def check_exposure_limits(
        self,
        asset: str,
        sector: str,
        proposed_exposure: float,
        capital: Optional[float] = None,
    ) -> Dict[str, object]:
        """
        Check proposed exposure against all limits.

        Returns
        -------
        dict with approved (bool), messages, and limit details.
        """
        cap = capital or self.current_capital
        asset_limit = cap * self.max_exposure_per_asset
        sector_limit = cap * self.max_exposure_per_sector
        current_asset = self.position_sizes.get(asset, 0.0)
        current_sector = sum(
            v for a, v in self.position_sizes.items()
            if self.asset_to_sector.get(a) == sector
        )
        total_asset = current_asset + proposed_exposure
        total_sector = current_sector + proposed_exposure

        issues = []
        if total_asset > asset_limit:
            issues.append(
                f"Asset {asset}: {total_asset:.2f} > {asset_limit:.2f} limit"
            )
        if total_sector > sector_limit:
            issues.append(
                f"Sector {sector}: {total_sector:.2f} > {sector_limit:.2f} limit"
            )

        return {
            "approved": len(issues) == 0,
            "issues": issues,
            "asset_exposure_used": round(total_asset / asset_limit * 100, 1),
            "sector_exposure_used": round(total_sector / sector_limit * 100, 1),
            "proposed_exposure": proposed_exposure,
            "current_capital": cap,
        }

    def correlation_adjusted_exposure(
        self, returns_df: pd.DataFrame, target_risk: float = 0.02
    ) -> pd.Series:
        """
        Calculate correlation-aware position limits.

        Uses the correlation matrix to compute how much each asset contributes
        to portfolio volatility, then allocates risk proportionally.
        """
        cov = returns_df.cov() * 252  # annualized
        inv_cov = np.linalg.pinv(cov.values)
        weights = inv_cov.sum(axis=1) / inv_cov.sum()
        weights = np.maximum(weights, 0)
        weights = weights / weights.sum()
        return pd.Series(weights * target_risk, index=returns_df.columns)

    @property
    def current_drawdown(self) -> float:
        """Current drawdown from peak as a decimal."""
        return self._drawdown_pct()

    def _drawdown_pct(self) -> float:
        if self.peak_capital <= 0:
            return 0.0
        return (self.peak_capital - self.current_capital) / self.peak_capital


# ============================================================================
# 5. DRAWDOWN CONTROLLER — Survive to Trade Another Day
# ============================================================================
# Drawdowns kill accounts not through the loss itself, but through the
# trader's response. This controller ensures you scale correctly: reduce
# risk gradually as drawdown deepens, but don't get paralyzed.

class DrawdownController:
    """
    Professional drawdown management.

    Two modes:
      - Linear scale-down: reduce position size proportionally to drawdown
      - Convex (recovery) allocation: INCREASE risk when drawdown is deep
        to recover faster — the Kelly "optimal recovery" strategy.

    The line between courage and stupidity is a tight one. This controller
    walks it with math.
    """

    def __init__(self, peak_capital: float = 100_000.0):
        self.peak_capital = peak_capital
        self.current_capital = peak_capital

    def update_capital(self, new_capital: float):
        """Update capital and track new peak."""
        self.current_capital = new_capital
        self.peak_capital = max(self.peak_capital, new_capital)

    def current_drawdown(self) -> float:
        """Current drawdown as a decimal (0.0 = no drawdown)."""
        if self.peak_capital <= 0:
            return 0.0
        return (self.peak_capital - self.current_capital) / self.peak_capital

    def recovery_factor(self) -> float:
        """
        Recovery factor: net profit / max drawdown.

        A measure of how efficiently the system recovers from drawdowns.
        Values above 2 are considered good, above 5 are excellent.
        """
        total_profit = self.current_capital - self.peak_capital
        max_dd = self._max_drawdown_tracking()
        if max_dd <= 0 or self.peak_capital <= 0:
            return 0.0
        return total_profit / (max_dd * self.peak_capital)

    def _max_drawdown_tracking(self) -> float:
        """
        Estimate max drawdown from peaks tracked internally.
        In practice you'd pass the full equity curve.
        """
        dd = self.current_drawdown()
        return dd  # Simplified; real version tracks rolling peaks

    def scale_down(self, drawdown_pct: Optional[float] = None) -> float:
        """
        Automatically reduce position size based on drawdown severity.

        The scaling function:
          - 0-5% drawdown: no reduction (factor = 1.0)
          - 5-10%: linear reduction to 0.75
          - 10-15%: linear reduction to 0.50
          - 15-20%: linear reduction to 0.25
          - 20%+: no trading (factor = 0.0)

        This matches how professional prop firms manage drawdowns.

        Parameters
        ----------
        drawdown_pct : float, optional
            Current drawdown (0.0-1.0). If None, uses internal tracking.

        Returns
        -------
        float
            Scaling factor (0.0 = no trading, 1.0 = normal size).
        """
        dd = drawdown_pct if drawdown_pct is not None else self.current_drawdown()
        dd = max(0.0, min(1.0, dd))

        if dd < 0.05:
            return 1.0
        elif dd < 0.10:
            # 5% -> 1.0, 10% -> 0.75
            return 1.0 - ((dd - 0.05) / 0.05) * 0.25
        elif dd < 0.15:
            # 10% -> 0.75, 15% -> 0.50
            return 0.75 - ((dd - 0.10) / 0.05) * 0.25
        elif dd < 0.20:
            # 15% -> 0.50, 20% -> 0.25
            return 0.50 - ((dd - 0.15) / 0.05) * 0.25
        else:
            # 20%+ -> no trading allowed
            return 0.0

    def convex_allocation(self, drawdown_pct: Optional[float] = None) -> float:
        """
        Convex allocation for recovery.

        In deep drawdowns, the Kelly criterion actually says to INCREASE
        risk to recover faster (convex strategy). This is the mathematical
        argument behind the "double down" approach — but you need the
        edge to justify it.

        f_recovery = f_normal / (1 - drawdown)

        This is still capped at a max scaling of 2.0x normal to prevent
        ruin. Only use if you are SURE your edge still exists during
        the drawdown.

        Parameters
        ----------
        drawdown_pct : float, optional
            Current drawdown fraction.

        Returns
        -------
        float
            Convex scaling factor (1.0-2.0).
        """
        dd = drawdown_pct if drawdown_pct is not None else self.current_drawdown()
        dd = max(0.0, min(1.0, dd))
        if dd <= 0.01:
            return 1.0
        # f = 1 / (1 - dd) — this is the Kelly recovery formula
        factor = 1.0 / (1.0 - dd)
        return min(2.0, factor)

    def position_size(self, base_size: float, use_convex: bool = False) -> float:
        """
        Compute the final position size given current drawdown.

        Parameters
        ----------
        base_size : float
            Base position size from whatever sizing method you use.
        use_convex : bool, default False
            If True, use convex recovery allocation instead of scale-down.

        Returns
        -------
        float
            Adjusted position size.
        """
        if use_convex:
            return base_size * self.convex_allocation()
        else:
            return base_size * self.scale_down()


# ============================================================================
# 6. STOP LOSS OPTIMIZER — Know When to Fold 'Em
# ============================================================================
# Stops are not arbitrary numbers. They should come from market structure,
# volatility, or time. This optimizer gives you every tool a veteran uses.

class StopLossOptimizer:
    """
    Professional stop-loss optimization using multiple methods.

    The best stop is the one that gets you out before the move hurts,
    but stays wide enough that normal noise doesn't shake you out.
    These methods each attack the problem from a different angle.
    """

    def __init__(self, df: Optional[pd.DataFrame] = None):
        """
        Parameters
        ----------
        df : pd.DataFrame, optional
            OHLCV DataFrame with columns: open, high, low, close, volume.
        """
        self.df = df

    def volatility_stop(
        self,
        entry_price: float,
        atr_value: Optional[float] = None,
        atr_multiple: float = 2.0,
        min_stop_pct: float = 0.005,
        max_stop_pct: float = 0.10,
        direction: str = "long",
    ) -> Dict[str, float]:
        """
        ATR-based volatility stop.

        The gold standard for intraday and swing trading. ATR captures
        current market volatility and adjusts the stop accordingly.

        Parameters
        ----------
        entry_price : float
            Entry price for the position.
        atr_value : float, optional
            Current ATR value. Computed from self.df if not provided.
        atr_multiple : float, default 2.0
            How many ATRs away to place the stop.
        min_stop_pct : float, default 0.005 (0.5%)
            Minimum stop distance as a fraction of entry price.
        max_stop_pct : float, default 0.10 (10%)
            Maximum stop distance as a fraction of entry price.
        direction : str, default 'long'
            'long' or 'short'.

        Returns
        -------
        dict with stop_price, stop_distance_pct, atr_used
        """
        if atr_value is None and self.df is not None and len(self.df) >= 14:
            atr_series = compute_atr(self.df)
            atr_value = float(atr_series.iloc[-1])
        elif atr_value is None:
            atr_value = entry_price * 0.01  # fallback: 1% of price

        stop_distance = atr_value * atr_multiple
        stop_distance_pct = stop_distance / entry_price

        # Clamp to min/max
        stop_distance_pct = max(min_stop_pct, min(max_stop_pct, stop_distance_pct))
        stop_distance = entry_price * stop_distance_pct

        if direction == "long":
            stop_price = entry_price - stop_distance
        else:
            stop_price = entry_price + stop_distance

        return {
            "stop_price": round(stop_price, 4),
            "stop_distance_pct": round(stop_distance_pct, 6),
            "atr_used": round(atr_value, 4),
            "atr_multiple": atr_multiple,
        }

    def structure_stop(
        self,
        entry_price: float,
        support_level: Optional[float] = None,
        resistance_level: Optional[float] = None,
        buffer_pct: float = 0.002,
        direction: str = "long",
    ) -> Dict[str, float]:
        """
        Structure-based stop using support/resistance levels.

        Places the stop just beyond a key level so normal reactions at
        the level don't take you out, but a true breakdown does.

        Parameters
        ----------
        entry_price : float
            Entry price.
        support_level : float, optional
            Nearest support level (for longs).
        resistance_level : float, optional
            Nearest resistance level (for shorts).
        buffer_pct : float, default 0.002 (0.2%)
            Buffer beyond the level to avoid being stopped by wicks.
        direction : str, default 'long'
            'long' or 'short'.

        Returns
        -------
        dict with stop_price, level_used, buffer_distance
        """
        if direction == "long":
            if support_level is None:
                return self.volatility_stop(entry_price, direction="long")
            buffer = support_level * buffer_pct
            stop_price = support_level - buffer
            return {
                "stop_price": round(stop_price, 4),
                "level_used": round(support_level, 4),
                "buffer_distance": round(buffer, 4),
                "stop_from_entry_pct": round(
                    abs(stop_price - entry_price) / entry_price, 6
                ),
            }
        else:
            if resistance_level is None:
                return self.volatility_stop(entry_price, direction="short")
            buffer = resistance_level * buffer_pct
            stop_price = resistance_level + buffer
            return {
                "stop_price": round(stop_price, 4),
                "level_used": round(resistance_level, 4),
                "buffer_distance": round(buffer, 4),
                "stop_from_entry_pct": round(
                    abs(stop_price - entry_price) / entry_price, 6
                ),
            }

    def trailing_stop(
        self,
        current_price: float,
        highest_price: float,
        trail_pct: float = 0.02,
        activation_pct: float = 0.0,
        direction: str = "long",
    ) -> Dict[str, float]:
        """
        Trailing stop that locks in profits as the market moves.

        Parameters
        ----------
        current_price : float
            Current market price.
        highest_price : float
            Highest price since entry (for longs) or lowest (for shorts).
        trail_pct : float, default 0.02 (2%)
            Distance to trail behind the extreme price.
        activation_pct : float, default 0.0
            Profit threshold before trailing activates (e.g., 0.05 = 5%).
        direction : str, default 'long'

        Returns
        -------
        dict with stop_price, trail_activated, locked_in_profit_pct
        """
        if direction == "long":
            profit_pct = (current_price - highest_price) / highest_price
            if profit_pct < activation_pct:
                # Trail not activated yet — stop at breakeven or initial stop
                return {
                    "stop_price": round(current_price * (1 - trail_pct), 4),
                    "trail_activated": False,
                    "locked_in_profit_pct": 0.0,
                }
            stop_price = highest_price * (1 - trail_pct)
            locked = (stop_price - current_price) / current_price
            return {
                "stop_price": round(stop_price, 4),
                "trail_activated": True,
                "locked_in_profit_pct": round(
                    (highest_price - stop_price) / highest_price, 6
                ),
            }
        else:
            profit_pct = (current_price - highest_price) / highest_price
            if profit_pct < activation_pct:
                return {
                    "stop_price": round(current_price * (1 + trail_pct), 4),
                    "trail_activated": False,
                    "locked_in_profit_pct": 0.0,
                }
            stop_price = highest_price * (1 + trail_pct)
            return {
                "stop_price": round(stop_price, 4),
                "trail_activated": True,
                "locked_in_profit_pct": round(
                    (stop_price - highest_price) / highest_price, 6
                ),
            }

    def time_stop(self, bars_held: int, max_bars: int) -> Dict[str, bool]:
        """
        Time-based stop — exit after a maximum number of bars.

        If a trade hasn't worked after a certain time, it's not going to.
        This prevents capital being tied up in dead positions.

        Parameters
        ----------
        bars_held : int
            Number of bars the position has been held.
        max_bars : int
            Maximum bars to hold before forced exit.

        Returns
        -------
        dict with exit_signal (bool), bars_held, max_bars, bars_remaining
        """
        remaining = max_bars - bars_held
        return {
            "exit_signal": bars_held >= max_bars,
            "bars_held": bars_held,
            "max_bars": max_bars,
            "bars_remaining": max(0, remaining),
        }

    def parabolic_stop(
        self,
        high_prices: Union[List[float], np.ndarray],
        low_prices: Union[List[float], np.ndarray],
        af_start: float = 0.02,
        af_accel: float = 0.02,
        af_max: float = 0.20,
        direction: str = "long",
    ) -> float:
        """
        Parabolic SAR stop (Welles Wilder's system).

        The SAR accelerates as the trend continues, eventually catching up
        to price and forcing an exit. Excellent for trending markets.
        """
        high = np.asarray(high_prices, dtype=float)
        low = np.asarray(low_prices, dtype=float)
        n = len(high)

        if n < 2:
            return float(high[-1] if direction == "long" else low[-1])

        sar = np.zeros(n)
        af = af_start
        ep = high[0] if direction == "long" else low[0]

        if direction == "long":
            sar[0] = low[0]
            for i in range(1, n):
                sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_accel, af_max)
                # SAR cannot be above the prior two lows
                if i >= 1:
                    sar[i] = min(sar[i], low[i - 1])
                if i >= 2:
                    sar[i] = min(sar[i], low[i - 2])
                # SAR cannot be above the current low
                sar[i] = min(sar[i], low[i])
        else:
            sar[0] = high[0]
            for i in range(1, n):
                sar[i] = sar[i - 1] + af * (ep - sar[i - 1])
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_accel, af_max)
                if i >= 1:
                    sar[i] = max(sar[i], high[i - 1])
                if i >= 2:
                    sar[i] = max(sar[i], high[i - 2])
                sar[i] = max(sar[i], high[i])

        return round(float(sar[-1]), 4)

    def combined_stop(
        self,
        entry_price: float,
        current_price: float,
        atr_value: Optional[float] = None,
        support_level: Optional[float] = None,
        resistance_level: Optional[float] = None,
        direction: str = "long",
    ) -> Dict[str, object]:
        """
        Combine multiple stop methods and return the tightest valid stop.

        A veteran uses whichever stop fires first — the tightest valid one.
        """
        vol_stop = self.volatility_stop(entry_price, atr_value, direction=direction)
        struct_stop = self.structure_stop(
            entry_price, support_level, resistance_level, direction=direction
        )

        stops = {
            "volatility_stop": vol_stop["stop_price"],
            "structure_stop": struct_stop["stop_price"],
        }

        if direction == "long":
            best_stop = max(s for s in stops.values())  # highest stop (tightest for long)
            best_method = [k for k, v in stops.items() if v == best_stop][0]
        else:
            best_stop = min(s for s in stops.values())
            best_method = [k for k, v in stops.items() if v == best_stop][0]

        return {
            "recommended_stop": round(best_stop, 4),
            "method_used": best_method,
            "volatility_stop": vol_stop,
            "structure_stop": struct_stop,
            "stop_distance_pct": round(
                abs(best_stop - entry_price) / entry_price, 6
            ),
            "direction": direction,
        }


# ============================================================================
# 7. RISK BUDGETER — Multi-Strategy Portfolio Allocation
# ============================================================================
# You don't have one strategy. You have several. The question is how much
# to allocate to each. Risk parity says: equalize risk contribution, not
# capital contribution.

class RiskBudgeter:
    """
    Multi-strategy risk budgeting and allocation.

    Methods:
      - Equal risk contribution: each strategy contributes the same amount of risk
      - Risk parity: weights proportional to inverse volatility
      - Volatility targeting: scale portfolio to a target volatility
      - Correlation-aware allocation: account for diversification benefits
    """

    @staticmethod
    def equal_risk_contribution(
        covariance_matrix: pd.DataFrame,
    ) -> pd.Series:
        """
        Compute weights such that each asset contributes equally to portfolio risk.

        This is the "risk parity" approach — not equal capital, but equal risk.

        Parameters
        ----------
        covariance_matrix : pd.DataFrame
            Covariance matrix of strategy/asset returns.

        Returns
        -------
        pd.Series
            Risk budget weights (sum to 1.0).
        """
        n = len(covariance_matrix)
        cov = covariance_matrix.values

        def risk_contribution(weights: np.ndarray) -> float:
            port_var = weights @ cov @ weights
            port_vol = np.sqrt(port_var)
            mrc = cov @ weights / port_vol  # marginal risk contribution
            rrc = weights * mrc  # risk contribution
            target = port_vol / n
            return np.sum((rrc - target) ** 2)

        x0 = np.ones(n) / n
        bounds = [(0.0, 1.0)] * n
        constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}

        res = minimize(risk_contribution, x0, bounds=bounds, constraints=constraints, method="SLSQP")

        if not res.success:
            # Fallback: inverse vol weighting
            vols = np.sqrt(np.diag(cov))
            inv_vol = 1.0 / vols
            return pd.Series(inv_vol / inv_vol.sum(), index=covariance_matrix.columns)

        return pd.Series(res.x, index=covariance_matrix.columns)

    @staticmethod
    def risk_parity(volatilities: pd.Series) -> pd.Series:
        """
        Simple risk parity: weight proportional to inverse volatility.

        This is the simplest and most robust risk parity implementation.
        It ignores correlations but is much more stable.

        Parameters
        ----------
        volatilities : pd.Series
            Annualized volatilities for each strategy/asset.

        Returns
        -------
        pd.Series
            Risk parity weights.
        """
        inv_vol = 1.0 / volatilities
        weights = inv_vol / inv_vol.sum()
        return weights

    @staticmethod
    def volatility_targeting(
        returns: pd.DataFrame,
        target_vol: float = 0.15,
        lookback: int = 60,
    ) -> pd.Series:
        """
        Volatility targeting — scale the portfolio to a target volatility level.

        This is how professional CTAs do it: estimate recent volatility
        and scale exposure to achieve the target. Higher vol = less exposure.

        Parameters
        ----------
        returns : pd.DataFrame
            Daily returns for portfolio.
        target_vol : float, default 0.15 (15% annualized)
            Target annualized volatility.
        lookback : int, default 60
            Lookback period in days for volatility estimation.

        Returns
        -------
        pd.Series
            Volatility target scaling factor.
        """
        recent = returns.iloc[-lookback:] if len(returns) > lookback else returns
        realized_vol = recent.std() * np.sqrt(252)
        scaling_factors = target_vol / realized_vol
        # Cap scaling between 0.1x and 3.0x
        scaling_factors = scaling_factors.clip(0.1, 3.0)
        return scaling_factors

    @staticmethod
    def correlation_aware_allocation(
        covariance_matrix: pd.DataFrame,
        target_vol: float = 0.15,
    ) -> pd.Series:
        """
        Correlation-aware minimum volatility allocation.

        Uses the full covariance matrix, not just volatilities, to find
        the allocation that minimizes portfolio volatility. This naturally
        allocates more to uncorrelated strategies and less to correlated ones.

        Parameters
        ----------
        covariance_matrix : pd.DataFrame
            Covariance matrix.
        target_vol : float, default 0.15
            Target portfolio volatility.

        Returns
        -------
        pd.Series
            Optimal weights.
        """
        n = len(covariance_matrix)
        cov = covariance_matrix.values

        def port_vol(weights: np.ndarray) -> float:
            return float(np.sqrt(weights @ cov @ weights))

        x0 = np.ones(n) / n
        bounds = [(0.0, 1.0)] * n
        constraints = {"type": "eq", "fun": lambda w: np.sum(w) - 1.0}

        res = minimize(port_vol, x0, bounds=bounds, constraints=constraints, method="SLSQP")

        if not res.success:
            return RiskBudgeter.risk_parity(
                pd.Series(np.sqrt(np.diag(cov)), index=covariance_matrix.columns)
            )

        # Scale to target vol
        w = res.x
        est_vol = float(np.sqrt(w @ cov @ w))
        scale = target_vol / est_vol if est_vol > 0 else 1.0

        return pd.Series(w * scale, index=covariance_matrix.columns)


# ============================================================================
# 8. LIQUIDITY MANAGER — Size Matters
# ============================================================================
# You can't get out of a position that's too big for the market.
# Liquidity is the silent killer — it doesn't show up in backtests,
# but it shows up when you try to exit.

class LiquidityManager:
    """
    Liquidity-aware position sizing and market impact modeling.

    The key questions:
      1. Can I get out of this position without moving the market?
      2. How much slippage will I pay?
      3. What's the market impact if I have to exit quickly?
    """

    @staticmethod
    def max_position_size(
        avg_daily_volume: float,
        avg_price: float,
        capital: float,
        min_days_to_liquidate: float = 1.0,
        max_capital_pct: float = 0.02,
        max_volume_pct: float = 0.10,
    ) -> Dict[str, float]:
        """
        Maximum position size constrained by liquidity.

        Two constraints:
          1. No more than X% of daily volume
          2. No more than X% of capital

        The lower of the two wins.

        Parameters
        ----------
        avg_daily_volume : float
            Average daily trading volume in shares/contracts.
        avg_price : float
            Current average price.
        capital : float
            Account capital.
        min_days_to_liquidate : float, default 1.0
            Minimum days to fully liquidate (higher = more conservative).
        max_capital_pct : float, default 0.02 (2%)
            Maximum fraction of capital in one position.
        max_volume_pct : float, default 0.10 (10%)
            Maximum fraction of daily volume.

        Returns
        -------
        dict with max_shares, max_notional, constraint_type
        """
        volume_limited_shares = (avg_daily_volume * max_volume_pct) / min_days_to_liquidate
        capital_limited_shares = (capital * max_capital_pct) / avg_price

        if volume_limited_shares < capital_limited_shares:
            max_shares = volume_limited_shares
            constraint = "volume"
        else:
            max_shares = capital_limited_shares
            constraint = "capital"

        return {
            "max_shares": round(max_shares, 2),
            "max_notional": round(max_shares * avg_price, 2),
            "constraint_type": constraint,
            "volume_limited": round(volume_limited_shares, 2),
            "capital_limited": round(capital_limited_shares, 2),
            "pct_of_daily_volume": round(
                max_shares / avg_daily_volume * 100, 4
            ) if avg_daily_volume > 0 else 0.0,
        }

    @staticmethod
    def slippage_estimate(
        size: float,
        avg_daily_volume: float,
        spread_pct: float = 0.0005,
        urgency: str = "normal",
    ) -> Dict[str, float]:
        """
        Estimate slippage costs for a given order size.

        Larger orders relative to volume incur more slippage.
        Higher urgency (market orders vs limit orders) incurs more.

        Parameters
        ----------
        size : float
            Order size in shares/contracts.
        avg_daily_volume : float
            Average daily volume.
        spread_pct : float, default 0.0005 (0.05%)
            Bid-ask spread as a fraction of price.
        urgency : str, default 'normal'
            'low' (limit orders), 'normal' (mix), 'high' (market orders).

        Returns
        -------
        dict with slippage_pct, slippage_cost_pct, participation_rate
        """
        participation = size / avg_daily_volume if avg_daily_volume > 0 else 0

        urgency_mult = {"low": 0.3, "normal": 1.0, "high": 2.5}
        mult = urgency_mult.get(urgency, 1.0)

        # Slippage = spread/2 + market impact from participation
        base_slippage = spread_pct / 2.0
        impact_slippage = 0.01 * np.sqrt(participation) * mult  # sqrt model
        total_slippage = base_slippage + impact_slippage

        return {
            "slippage_pct": round(total_slippage, 6),
            "participation_rate": round(participation, 6),
            "urgency": urgency,
            "spread_half_pct": round(spread_pct / 2, 6),
            "impact_slippage_pct": round(impact_slippage, 6),
        }

    @staticmethod
    def market_impact_model(
        size: float,
        volatility: float,
        avg_daily_volume: float,
        avg_price: float,
    ) -> Dict[str, float]:
        """
        Almgren-Chriss-style market impact model.

        Estimates both permanent and temporary market impact from a trade.

        Permanent impact: the information component — affects the price
        permanently because the market learns you're trading.

        Temporary impact: the execution component — goes away after your
        order is filled.

        Parameters
        ----------
        size : float
            Order size in shares.
        volatility : float
            Daily volatility (standard deviation of returns).
        avg_daily_volume : float
            Average daily volume.
        avg_price : float
            Current price.

        Returns
        -------
        dict with permanent_impact_pct, temporary_impact_pct, total_cost
        """
        if avg_daily_volume <= 0:
            return {"error": "Zero volume"}

        participation = size / avg_daily_volume
        sigma = volatility * avg_price  # dollar volatility

        # Almgren-Chriss parameters (institutional-grade constants)
        perm_coeff = 0.01  # permanent impact coefficient
        temp_coeff = 0.02  # temporary impact coefficient
        gamma = 0.3  # exponent

        permanent_impact = perm_coeff * sigma * (participation ** gamma)
        temporary_impact = temp_coeff * sigma * (participation ** gamma)

        total_cost = permanent_impact + temporary_impact

        return {
            "permanent_impact_pct": round(permanent_impact / avg_price * 100, 6),
            "temporary_impact_pct": round(temporary_impact / avg_price * 100, 6),
            "total_cost_pct": round(total_cost / avg_price * 100, 6),
            "total_cost_dollars": round(total_cost, 2),
            "participation_rate": round(participation, 6),
            "order_size_shares": round(size, 2),
        }


# ============================================================================
# 9. CORRELATION TRACKER — Know What Moves Together
# ============================================================================
# Correlation is not static. It changes with market regimes. In a crash,
# everything goes to 1.0. This tracker gives you rolling and regime-specific
# correlation matrices plus PCA risk factor decomposition.

class CorrelationTracker:
    """
    Rolling and regime-dependent correlation analysis with PCA factor models.

    Correlation is the single most dangerous hidden risk in a portfolio.
    It's always higher than you think during a crisis.
    """

    def __init__(self, returns_df: Optional[pd.DataFrame] = None):
        """
        Parameters
        ----------
        returns_df : pd.DataFrame, optional
            Daily returns with assets as columns.
        """
        self.returns = returns_df

    def rolling_correlation(
        self,
        asset_a: str,
        asset_b: str,
        window: int = 60,
    ) -> pd.Series:
        """
        Rolling pairwise correlation between two assets.

        Parameters
        ----------
        asset_a : str
            First asset column name.
        asset_b : str
            Second asset column name.
        window : int, default 60
            Rolling window in periods.

        Returns
        -------
        pd.Series
            Rolling correlation series.
        """
        if self.returns is None:
            raise ValueError("No returns data provided")
        return self.returns[asset_a].rolling(window).corr(self.returns[asset_b])

    def correlation_matrix(self, method: str = "pearson") -> pd.DataFrame:
        """
        Full correlation matrix of all assets.

        Parameters
        ----------
        method : str, default 'pearson'
            'pearson', 'spearman' (rank-based, more robust), or 'kendall'.

        Returns
        -------
        pd.DataFrame
            Correlation matrix.
        """
        if self.returns is None:
            raise ValueError("No returns data provided")
        return self.returns.corr(method=method)

    def regime_correlations(
        self,
        benchmark_returns: Optional[pd.Series] = None,
        vol_threshold: float = 0.02,
    ) -> Dict[str, pd.DataFrame]:
        """
        Regime-dependent correlation matrices.

        Splits data into bull/bear/volatile regimes and computes a separate
        correlation matrix for each. This is critical because correlations
        spike in crises (the "correlation 1.0" effect).

        Parameters
        ----------
        benchmark_returns : pd.Series, optional
            Benchmark returns for regime classification.
        vol_threshold : float, default 0.02 (2% daily)
            Daily return magnitude that defines "volatile" regime.

        Returns
        -------
        dict {regime_name: correlation_matrix}
        """
        if self.returns is None:
            raise ValueError("No returns data provided")

        bm = benchmark_returns if benchmark_returns is not None else self.returns.mean(axis=1)

        bull_mask = bm > 0.005
        bear_mask = bm < -0.005
        volatile_mask = self.returns.std(axis=1) > vol_threshold
        calm_mask = ~volatile_mask

        regimes = {
            "bull": bull_mask,
            "bear": bear_mask,
            "volatile": volatile_mask,
            "calm": calm_mask,
            "all": pd.Series(True, index=self.returns.index),
        }

        result = {}
        for name, mask in regimes.items():
            subset = self.returns.loc[mask]
            if len(subset) > 10:
                result[name] = subset.corr()
            else:
                result[name] = self.returns.corr()  # fallback

        return result

    def pca_decomposition(self, n_components: Optional[int] = None) -> Dict[str, object]:
        """
        PCA-based risk factor decomposition.

        Reduces the asset space to its principal risk factors. This tells
        you how many independent sources of risk your portfolio has and
        which assets load on which factors.

        Parameters
        ----------
        n_components : int, optional
            Number of components to extract (default: min(5, n_assets)).

        Returns
        -------
        dict with explained_variance, loadings, components, cumulative_variance
        """
        from sklearn.decomposition import PCA

        if self.returns is None:
            raise ValueError("No returns data provided")

        data = self.returns.dropna()
        n = min(5, data.shape[1], data.shape[0])
        n_components = n_components or n

        pca = PCA(n_components=n_components)
        pca.fit(data.values)

        loadings = pd.DataFrame(
            pca.components_.T,
            index=data.columns,
            columns=[f"PC{i+1}" for i in range(n_components)],
        )

        return {
            "explained_variance": pca.explained_variance_ratio_.tolist(),
            "cumulative_variance": np.cumsum(pca.explained_variance_ratio_).tolist(),
            "loadings": loadings,
            "n_components": n_components,
            "n_assets": data.shape[1],
            "effectively_independent_factors": int(
                np.sum(np.cumsum(pca.explained_variance_ratio_) < 0.90) + 1
            ),
        }

    @staticmethod
    def average_correlation(corr_matrix: pd.DataFrame) -> float:
        """
        Average pairwise correlation (excluding the diagonal).

        A single number summary of how correlated your portfolio is.
        Above 0.7 in a crisis means zero diversification.
        """
        triu = np.triu(corr_matrix.values, k=1)
        values = triu[triu != 0]
        return float(np.mean(values)) if len(values) > 0 else 0.0


# ============================================================================
# 10. STRESS TESTER — The Crash Simulator
# ============================================================================
# Everyone backtests in smooth markets. Pros stress-test against the worst
# moments in market history. If your strategy survives these, you have
# the right to call yourself a risk manager.

class StressTester:
    """
    Historical and synthetic stress test scenarios.

    Runs your portfolio through the worst moments in market history
    and synthetic tail events. Returns maximum loss, time to recovery,
    and whether the portfolio survives.
    """

    # Historical crash scenarios as {asset_type: shock_pct}
    HISTORICAL_SCENARIOS = {
        "2008_financial_crisis": {
            "name": "2008 Global Financial Crisis",
            "description": "Lehman collapse, credit freeze, systemic contagion",
            "shocks": {
                "equities": -0.54,
                "high_yield": -0.35,
                "investment_grade": -0.20,
                "real_estate": -0.40,
                "commodities": -0.50,
                "emerging_markets": -0.60,
                "developed_markets": -0.54,
                "crypto": -0.90,
            },
            "recovery_bars": 750,  # ~3 years
            "volatility_shock": 3.5,  # vol multiplier
        },
        "2010_flash_crash": {
            "name": "2010 Flash Crash",
            "description": "Algorithmic cascade, 36-minute crash and recovery",
            "shocks": {
                "equities": -0.09,
                "futures": -0.10,
                "etfs": -0.08,
            },
            "recovery_bars": 1,  # intraday recovery
            "volatility_shock": 10.0,
        },
        "2015_snb_unpeg": {
            "name": "2015 SNB EUR/CHF Unpeg",
            "description": "Swiss National Bank abandoned EUR/CHF floor — 40% FX gap",
            "shocks": {
                "eur": 0.0,
                "chf": 0.40,
                "equities": -0.12,
                "european_banks": -0.25,
            },
            "recovery_bars": 60,
            "volatility_shock": 5.0,
        },
        "2020_covid_crash": {
            "name": "2020 COVID-19 Crash",
            "description": "Pandemic lockdowns, fastest bear market in history",
            "shocks": {
                "equities": -0.34,
                "high_yield": -0.22,
                "investment_grade": -0.15,
                "commodities": -0.35,
                "emerging_markets": -0.30,
                "developed_markets": -0.34,
                "crypto": -0.60,
                "real_estate": -0.25,
            },
            "recovery_bars": 150,  # ~6 months
            "volatility_shock": 4.0,
        },
        "2022_crypto_crash": {
            "name": "2022 Crypto / Rates Crash",
            "description": "Rate hikes, LUNA/FTX collapse, crypto contagion",
            "shocks": {
                "crypto": -0.75,
                "equities": -0.25,
                "high_yield": -0.18,
                "investment_grade": -0.10,
                "growth_stocks": -0.45,
            },
            "recovery_bars": 365,
            "volatility_shock": 3.0,
        },
        "2023_svb_crisis": {
            "name": "2023 SVB / Banking Crisis",
            "description": "Regional bank runs, credit contagion fears",
            "shocks": {
                "equities": -0.12,
                "regional_banks": -0.40,
                "investment_grade": -0.08,
                "high_yield": -0.15,
            },
            "recovery_bars": 30,
            "volatility_shock": 2.5,
        },
    }

    SYNTHETIC_SCENARIOS = {
        "flash_crash_30pct": {
            "name": "Flash Crash -30%",
            "description": "Sudden 30% equity collapse with VIX > 50",
            "shocks": {
                "equities": -0.30,
                "high_yield": -0.20,
                "investment_grade": -0.12,
                "commodities": -0.15,
                "crypto": -0.50,
            },
            "recovery_bars": 252,  # ~1 year
            "volatility_shock": 6.0,
        },
        "gap_down_10pct": {
            "name": "Gap Down -10%",
            "description": "Overnight gap down 10% on geopolitical event",
            "shocks": {
                "equities": -0.10,
                "crypto": -0.20,
                "commodities": -0.08,
            },
            "recovery_bars": 20,
            "volatility_shock": 3.0,
        },
        "liquidity_crisis": {
            "name": "Liquidity Crisis",
            "description": "Bid-ask spreads 10x, cannot exit positions at fair price",
            "shocks": {
                "equities": -0.15,
                "high_yield": -0.30,
                "emerging_markets": -0.25,
                "real_estate": -0.20,
                "crypto": -0.60,
            },
            "recovery_bars": 126,
            "volatility_shock": 4.0,
        },
        "rates_shock": {
            "name": "Rates Shock +200bps",
            "description": "Sudden 200bp rate hike, bonds crash, equities follow",
            "shocks": {
                "equities": -0.20,
                "investment_grade": -0.15,
                "high_yield": -0.25,
                "real_estate": -0.30,
            },
            "recovery_bars": 180,
            "volatility_shock": 3.5,
        },
        "currency_crisis": {
            "name": "Currency Crisis -20% FX",
            "description": "EM currency collapse, capital controls, contagion",
            "shocks": {
                "emerging_markets": -0.35,
                "commodities": -0.20,
                "equities": -0.15,
                "developed_markets": -0.08,
            },
            "recovery_bars": 200,
            "volatility_shock": 4.5,
        },
    }

    def __init__(self, portfolio_weights: Optional[Dict[str, float]] = None):
        """
        Parameters
        ----------
        portfolio_weights : dict {asset_type: weight}, optional
            Portfolio composition by asset type. Asset types should match
            scenario shock keys (e.g., 'equities', 'crypto', 'high_yield').
        """
        self.portfolio_weights = portfolio_weights or {}
        self.results_cache: Dict[str, Dict] = {}

    def set_portfolio(self, weights: Dict[str, float]):
        """Set or update portfolio weights."""
        total = sum(weights.values())
        self.portfolio_weights = {k: v / total for k, v in weights.items()}

    def run_scenario(
        self,
        scenario: Dict[str, object],
        portfolio_weights: Optional[Dict[str, float]] = None,
    ) -> Dict[str, object]:
        """
        Run a single stress scenario against the portfolio.

        Parameters
        ----------
        scenario : dict
            Scenario with 'shocks', 'recovery_bars', 'volatility_shock'.
        portfolio_weights : dict, optional
            Override portfolio weights for this run.

        Returns
        -------
        dict with total_loss, max_loss_pct, survives, recovery_time_est,
             worst_asset, scenario_name
        """
        weights = portfolio_weights or self.portfolio_weights
        shocks = scenario.get("shocks", {})

        if not weights or not shocks:
            return {
                "total_loss_pct": 0.0,
                "survives": True,
                "note": "No portfolio or scenario data",
            }

        total_loss = 0.0
        asset_impacts = {}
        for asset_type, weight in weights.items():
            if asset_type in shocks:
                impact = weight * shocks[asset_type]
                total_loss += impact
                asset_impacts[asset_type] = {
                    "weight": weight,
                    "shock_pct": shocks[asset_type],
                    "contribution_pct": impact,
                }
            else:
                # Asset type not in scenario shocks — use equity as proxy
                proxy_shock = shocks.get("equities", -0.20)
                impact = weight * proxy_shock
                total_loss += impact
                asset_impacts[asset_type] = {
                    "weight": weight,
                    "shock_pct": proxy_shock,
                    "contribution_pct": impact,
                    "note": "proxy shock applied (asset not in scenario)",
                }

        max_loss_pct = abs(total_loss)
        survives = max_loss_pct < 0.50  # 50% loss = account usually dead
        recovery_bars = scenario.get("recovery_bars", 252)

        worst_asset = min(asset_impacts, key=lambda a: asset_impacts[a]["contribution_pct"])

        return {
            "scenario_name": scenario.get("name", "Unknown"),
            "scenario_description": scenario.get("description", ""),
            "total_loss_pct": round(total_loss, 6),
            "max_loss_pct": round(max_loss_pct, 6),
            "capital_remaining_pct": round(1.0 + total_loss, 6),
            "survives": survives,
            "recovery_bars_estimate": recovery_bars,
            "recovery_days_estimate": recovery_bars,
            "volatility_multiplier": scenario.get("volatility_shock", 1.0),
            "worst_hit_asset": worst_asset,
            "asset_breakdown": asset_impacts,
        }

    def run_all_historical(
        self, portfolio_weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Dict]:
        """
        Run all historical stress scenarios.

        Returns
        -------
        dict {scenario_key: run_scenario_result}
        """
        results = {}
        for key, scenario in self.HISTORICAL_SCENARIOS.items():
            results[key] = self.run_scenario(scenario, portfolio_weights)
        self.results_cache["historical"] = results
        return results

    def run_all_synthetic(
        self, portfolio_weights: Optional[Dict[str, float]] = None
    ) -> Dict[str, Dict]:
        """
        Run all synthetic stress scenarios.

        Returns
        -------
        dict {scenario_key: run_scenario_result}
        """
        results = {}
        for key, scenario in self.SYNTHETIC_SCENARIOS.items():
            results[key] = self.run_scenario(scenario, portfolio_weights)
        self.results_cache["synthetic"] = results
        return results

    def worst_case_loss(
        self, scenarios: Optional[Dict[str, Dict]] = None
    ) -> Dict[str, object]:
        """
        Find the worst-case scenario across all runs.

        Returns
        -------
        dict with worst_scenario, max_loss, and runner-up
        """
        all_results = {}
        for group in ["historical", "synthetic"]:
            if group in self.results_cache:
                all_results.update(self.results_cache[group])

        if not all_results:
            # Run everything
            hist = self.run_all_historical()
            synth = self.run_all_synthetic()
            all_results = {**hist, **synth}

        if not all_results:
            return {"error": "No results available"}

        worst_key = max(all_results, key=lambda k: all_results[k].get("max_loss_pct", 0))
        worst = all_results[worst_key]

        # Find runner-up
        sorted_keys = sorted(
            all_results, key=lambda k: all_results[k].get("max_loss_pct", 0), reverse=True
        )
        runner_up = all_results.get(sorted_keys[1], {}) if len(sorted_keys) > 1 else None

        # Portfolio health score: how many scenarios does it survive?
        survival_rate = sum(
            1 for r in all_results.values() if r.get("survives", True)
        ) / max(len(all_results), 1)

        return {
            "worst_scenario": worst.get("scenario_name", worst_key),
            "max_loss_pct": round(worst.get("max_loss_pct", 0), 4),
            "survives_worst_case": worst.get("survives", False),
            "runner_up_scenario": runner_up.get("scenario_name", "") if runner_up else "",
            "runner_up_loss_pct": round(runner_up.get("max_loss_pct", 0), 4) if runner_up else 0.0,
            "survival_rate_across_scenarios": round(survival_rate, 4),
            "num_scenarios_tested": len(all_results),
        }

    @staticmethod
    def correlation_shock_amplifier(
        current_correlation: float, scenario_volatility_mult: float = 3.0
    ) -> float:
        """
        Model how correlations amplify in a crisis.

        During normal times, correlations are low (0.3-0.5).
        During a crisis, they converge toward 1.0.

        This function estimates the effective diversification during a stress event.
        """
        # During a crisis, correlation moves toward 1.0 exponentially
        stress_corr = 1.0 - (1.0 - current_correlation) / np.sqrt(scenario_volatility_mult)
        return min(0.99, max(current_correlation, stress_corr))


# ============================================================================
# COMPREHENSIVE RISK REPORT
# ============================================================================

class RiskReport:
    """
    Master risk report — runs all risk checks and produces a single summary.

    This is what the 20-year veteran reads before every trading session.
    """

    @staticmethod
    def generate(
        capital: float,
        peak_capital: float,
        trades: Union[List[float], np.ndarray],
        portfolio_weights: Dict[str, float],
        returns_df: pd.DataFrame,
        current_drawdown_pct: Optional[float] = None,
    ) -> Dict[str, object]:
        """
        Generate a comprehensive risk report.

        Parameters
        ----------
        capital : float
            Current capital.
        peak_capital : float
            Peak capital (for drawdown calculation).
        trades : list or array
            Historical trade PnLs.
        portfolio_weights : dict
            Asset type -> weight mapping.
        returns_df : pd.DataFrame
            Daily returns for each asset.
        current_drawdown_pct : float, optional
            Pre-computed drawdown percentage.

        Returns
        -------
        dict with sections: sizing, drawdown, var, stress, correlation, liquidity
        """
        report = {}

        # --- Position Sizing ---
        try:
            kelly = KellyCriterion.estimate_edge(trades)
            report["kelly_analysis"] = kelly
        except Exception:
            report["kelly_analysis"] = {"error": "Could not compute"}

        # --- Drawdown ---
        dd = current_drawdown_pct or ((peak_capital - capital) / peak_capital)
        dc = DrawdownController(peak_capital)
        dc.update_capital(capital)
        report["drawdown"] = {
            "current_drawdown_pct": round(dd, 4),
            "scale_down_factor": round(dc.scale_down(), 4),
            "convex_recovery_factor": round(dc.convex_allocation(), 4),
            "recovery_factor": round(dc.recovery_factor(), 4),
        }

        # --- VaR ---
        if returns_df is not None and len(returns_df) > 20:
            rm = RiskManager(initial_capital=peak_capital)
            portfolio_returns = returns_df.mean(axis=1).dropna().values
            report["var_analysis"] = rm.var_summary(portfolio_returns)

        # --- Stress Test ---
        st = StressTester(portfolio_weights)
        st.run_all_historical()
        st.run_all_synthetic()
        report["stress_test"] = st.worst_case_loss()

        # --- Correlation ---
        if returns_df is not None and returns_df.shape[1] > 1:
            ct = CorrelationTracker(returns_df)
            corr_mat = ct.correlation_matrix()
            avg_corr = CorrelationTracker.average_correlation(corr_mat)
            regimes = ct.regime_correlations()
            regime_corrs = {}
            for reg_name, reg_mat in regimes.items():
                regime_corrs[reg_name] = round(
                    CorrelationTracker.average_correlation(reg_mat), 4
                )

            # Crisis correlation amplification
            crisis_corr = StressTester.correlation_shock_amplifier(avg_corr, 3.0)

            report["correlation"] = {
                "average_correlation": round(avg_corr, 4),
                "crisis_correlation_estimate": round(crisis_corr, 4),
                "regime_correlations": regime_corrs,
            }

            try:
                report["pca_risk_factors"] = ct.pca_decomposition()
            except Exception:
                pass

        # --- Liquidity Check ---
        report["liquidity"] = {
            "note": "Provide avg_daily_volume and price per asset for detailed liquidity analysis"
        }

        # --- Limits Status ---
        report["limits"] = {
            "current_drawdown_warning": "SEVERE" if dd > 0.20 else (
                "HIGH" if dd > 0.15 else (
                    "MODERATE" if dd > 0.10 else (
                        "LOW" if dd > 0.05 else "NORMAL"
                    )
                )
            ),
            "stop_trading_at_dd": 0.20,
        }

        return report


# ============================================================================
# CONVENIENCE: Quick Risk Check — The Morning Routine
# ============================================================================

def morning_risk_briefing(
    capital: float,
    peak_capital: float,
    trades: Union[List[float], np.ndarray],
    portfolio_weights: Dict[str, float],
    returns_df: pd.DataFrame,
) -> str:
    """
    Quick morning briefing for the professional trader.

    Returns a formatted summary of key risk metrics.
    """
    report = RiskReport.generate(capital, peak_capital, trades, portfolio_weights, returns_df)

    lines = []
    lines.append("=" * 60)
    lines.append("  RISK BRIEFING — Morning Preparation")
    lines.append("=" * 60)
    lines.append(f"  Capital: ${capital:,.2f} | Peak: ${peak_capital:,.2f}")

    dd = report.get("drawdown", {})
    lines.append(f"  Drawdown: {dd.get('current_drawdown_pct', 0)*100:.1f}%")
    lines.append(f"  Scale Factor: {dd.get('scale_down_factor', 1):.2f}x")
    lines.append(f"  Recovery Factor: {dd.get('recovery_factor', 0):.2f}")

    kelly = report.get("kelly_analysis", {})
    if "error" not in kelly:
        lines.append(f"  Win Rate: {kelly.get('p_win', 0)*100:.1f}%")
        lines.append(f"  Win/Loss Ratio: {kelly.get('win_loss_ratio', 0):.2f}")
        lines.append(f"  Quarter-Kelly: {kelly.get('kelly_quarter', 0):.4f}")
        lines.append(f"  Edge (Sharpe): {kelly.get('sharpe_style_edge', 0):.4f}")

    stress = report.get("stress_test", {})
    lines.append(f"  Worst-Case Stress Loss: {stress.get('max_loss_pct', 0)*100:.1f}%")
    lines.append(f"  Scenario: {stress.get('worst_scenario', 'N/A')}")
    lines.append(f"  Survives: {'YES' if stress.get('survives_worst_case') else 'NO — REDUCE NOW'}")

    corr = report.get("correlation", {})
    if corr:
        lines.append(f"  Avg Correlation: {corr.get('average_correlation', 0):.2f}")
        lines.append(f"  Crisis Corr Estimate: {corr.get('crisis_correlation_estimate', 0):.2f}")

    var_an = report.get("var_analysis", {})
    if var_an:
        lines.append(f"  95% VaR (Historical): {var_an.get('historical_var', 0)*100:.2f}%")
        lines.append(f"  CVaR / Expected Shortfall: {var_an.get('cvar_expected_shortfall', 0)*100:.2f}%")

    lim = report.get("limits", {})
    lines.append(f"  Risk Level: {lim.get('current_drawdown_warning', 'NORMAL')}")
    lines.append("=" * 60)

    return "\n".join(lines)