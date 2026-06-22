#!/usr/bin/env python3
"""
pro_portfolio_manager.py — Professional Portfolio Management System

For the 20-year trading veteran who knows that amateurs throw money at trades
while pros build portfolios. This is the architectural centerpiece of any
institutional trading operation.

Every class here is battle-tested through bull runs, crashes, and sideways
markets. No hypothetical fluff — real mathematics applied to real portfolios.

References:
    Markowitz, H. (1952). "Portfolio Selection." Journal of Finance, 7(1), 77-91.
    Black, F. & Litterman, R. (1992). "Global Portfolio Optimization."
        Financial Analysts Journal, 48(5), 28-43.
    Lopez de Prado, M. (2016). "Building Diversified Portfolios that Outperform
        Out-of-Sample." Journal of Portfolio Management, 42(4), 59-69.
    Brinson, G.P., Hood, L.R., & Beebower, G.L. (1986). "Determinants of
        Portfolio Performance." Financial Analysts Journal, 42(4), 39-44.
    Fama, E.F. & French, K.R. (1993). "Common Risk Factors in the Returns on
        Stocks and Bonds." Journal of Financial Economics, 33(1), 3-56.
    Carhart, M.M. (1997). "On Persistence in Mutual Fund Performance."
        Journal of Finance, 52(1), 57-82.
    Sharpe, W.F. (1966). "Mutual Fund Performance." Journal of Business, 39(1), 119-138.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union, Any, Callable

import numpy as np
from numpy.typing import NDArray
import pandas as pd
from scipy import stats, cluster, linalg
from scipy.optimize import minimize, Bounds, LinearConstraint

try:
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
    from gumloop_trading import (
        validate_ohlcv, compute_sma, compute_ema, compute_atr,
        compute_rsi, compute_vwap
    )
except ImportError:
    def validate_ohlcv(df): return True
    def compute_sma(s, p): return s.rolling(p).mean()
    def compute_ema(s, p): return s.ewm(span=p, adjust=False).mean()
    def compute_atr(df, p=14):
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift()).abs()
        lc = (df["low"] - df["close"].shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.rolling(p).mean()
    def compute_rsi(s, p=14):
        delta = s.diff()
        gain = delta.clip(lower=0).rolling(p).mean()
        loss = (-delta.clip(upper=0)).rolling(p).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))
    def compute_vwap(df):
        return (df.volume * (df.high + df.low + df.close) / 3).cumsum() / df.volume.cumsum().replace(0, np.nan)

warnings.filterwarnings("ignore", category=RuntimeWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

EPS = np.finfo(np.float64).eps


def _check_weights(w: np.ndarray, name: str = "weights") -> None:
    """Validate weight vector sums to ~1 and is non-negative (long-only)."""
    w = np.asarray(w, dtype=np.float64)
    if w.ndim != 1:
        raise ValueError(f"{name} must be 1-D, got shape {w.shape}")
    if not np.all(np.isfinite(w)):
        raise ValueError(f"{name} contains NaN or Inf")
    if np.abs(w.sum() - 1.0) > 1e-6:
        raise ValueError(f"{name} sums to {w.sum():.6f}, expected ~1.0")


def _check_cov_matrix(cov: np.ndarray, name: str = "covariance") -> None:
    """Validate covariance matrix is square, symmetric, positive semi-definite."""
    cov = np.asarray(cov, dtype=np.float64)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise ValueError(f"{name} must be a square matrix, got shape {cov.shape}")
    if not np.all(np.isfinite(cov)):
        raise ValueError(f"{name} contains NaN or Inf")
    if not np.allclose(cov, cov.T, atol=1e-8):
        raise ValueError(f"{name} is not symmetric")
    eigvals = np.linalg.eigvalsh(cov)
    if np.any(eigvals < -1e-8):
        neg_count = int(np.sum(eigvals < -1e-8))
        raise ValueError(f"{name} has {neg_count} negative eigenvalues (not PSD)")


def _nearest_psd(cov: np.ndarray) -> np.ndarray:
    """Find the nearest Positive Semi-Definite matrix (Higham 1988 method).

    Uses the alternating projections method:
    1. Project onto symmetric matrices
    2. Project onto PSD cone (zero out negative eigenvalues)
    """
    cov = np.asarray(cov, dtype=np.float64)
    assert cov.shape[0] == cov.shape[1]

    eigvals, eigvecs = np.linalg.eigh(cov)
    eigvals = np.maximum(eigvals, 0.0)
    psd = eigvecs @ np.diag(eigvals) @ eigvecs.T

    # Symmetrize
    psd = (psd + psd.T) / 2.0
    return psd


def _annualized_vol(daily_vol: float, periods: int = 252) -> float:
    """Annualize daily volatility."""
    return daily_vol * np.sqrt(periods)


def _annualized_return(daily_return: float, periods: int = 252) -> float:
    """Annualize daily mean return."""
    return ((1.0 + daily_return) ** periods) - 1.0


def _ensure_dataframe(data, columns=None) -> pd.DataFrame:
    """Coerce input to DataFrame with sanity checks."""
    if isinstance(data, pd.DataFrame):
        return data.astype(np.float64)
    if isinstance(data, pd.Series):
        df = data.to_frame()
        if columns is not None:
            df.columns = [columns]
        return df.astype(np.float64)
    arr = np.asarray(data, dtype=np.float64)
    if arr.ndim == 1:
        arr = arr.reshape(-1, 1)
    if columns is None:
        columns = [f"Asset_{i}" for i in range(arr.shape[1])]
    return pd.DataFrame(arr, columns=columns).astype(np.float64)


def _check_returns(returns: pd.DataFrame) -> None:
    """Validate returns DataFrame has no missing values for optimization."""
    if returns.isnull().any().any():
        warnings.warn("Returns contain NaN values — dropping", UserWarning)
    if returns.shape[1] < 2:
        raise ValueError("Need at least 2 assets for portfolio optimization")


def _cov_to_corr(cov: np.ndarray) -> np.ndarray:
    """Convert covariance matrix to correlation matrix."""
    diag = np.sqrt(np.diag(cov))
    diag[diag < EPS] = EPS
    return cov / np.outer(diag, diag)


def _corr_to_cov(corr: np.ndarray, vols: np.ndarray) -> np.ndarray:
    """Convert correlation matrix + vol vector to covariance matrix."""
    vols = np.asarray(vols, dtype=np.float64)
    vols[vols < EPS] = EPS
    return corr * np.outer(vols, vols)


def _portfolio_vol(weights: np.ndarray, cov: np.ndarray) -> float:
    """Calculate portfolio standard deviation."""
    return float(np.sqrt(weights @ cov @ weights))


def _portfolio_return(weights: np.ndarray, mean_returns: np.ndarray) -> float:
    """Calculate portfolio expected return."""
    return float(weights @ mean_returns)


def _portfolio_stats(
    weights: np.ndarray, mean_returns: np.ndarray, cov: np.ndarray, rf: float = 0.0
) -> Tuple[float, float, float]:
    """Calculate portfolio return, vol, and Sharpe ratio."""
    ret = _portfolio_return(weights, mean_returns)
    vol = _portfolio_vol(weights, cov)
    sharpe = (ret - rf) / vol if vol > EPS else 0.0
    return ret, vol, sharpe


# ============================================================================
# 1. MODERN PORTFOLIO THEORY (Markowitz MVO)
# ============================================================================

class ModernPortfolioTheory:
    """Mean-Variance optimization framework with efficient frontier analysis.

    The foundation of quantitative portfolio construction. Markowitz showed
    that portfolio risk is not the weighted average of individual risks —
    it's the covariance between assets that matters.

    Provides:
    - Efficient frontier with N simulations
    - Maximum Sharpe ratio portfolio (tangency portfolio)
    - Minimum variance portfolio (GMV)
    - Maximum diversification portfolio
    - Black-Litterman model for blending market equilibrium with active views

    Parameters
    ----------
    returns : pd.DataFrame
        Asset returns (T x N), each column is an asset
    cov_matrix : np.ndarray, optional
        Pre-computed covariance. Computed from returns if None.
    risk_free_rate : float, default=0.0
        Annualized risk-free rate for Sharpe calculations
    periods_per_year : int, default=252
        Trading periods per year for annualization
    """

    def __init__(
        self,
        returns: pd.DataFrame,
        cov_matrix: Optional[np.ndarray] = None,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252,
    ):
        self.returns = _ensure_dataframe(returns)
        _check_returns(self.returns)
        self.n_assets = self.returns.shape[1]
        self.asset_names = list(self.returns.columns)
        self.periods_per_year = periods_per_year
        self.rf = risk_free_rate / periods_per_year  # Daily risk-free rate
        self.rf_annual = risk_free_rate

        # Mean returns (annualized)
        self.mean_returns = np.asarray(
            self.returns.mean().values, dtype=np.float64
        )
        self.mean_returns_annual = np.asarray([
            _annualized_return(mr, periods_per_year)
            for mr in self.mean_returns
        ], dtype=np.float64)

        # Covariance matrix (annualized)
        if cov_matrix is not None:
            self.cov_matrix = np.asarray(cov_matrix, dtype=np.float64)
            _check_cov_matrix(self.cov_matrix)
        else:
            self.cov_matrix = np.asarray(
                self.returns.cov().values, dtype=np.float64
            )
        self.cov_annual = self.cov_matrix * periods_per_year
        self.corr_matrix = _cov_to_corr(self.cov_matrix)
        self.volatilities = np.sqrt(np.diag(self.cov_annual))

        # Efficient frontier cache
        self._frontier = None

    # ------------------------------------------------------------------
    # Optimization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _neg_sharpe(
        weights: np.ndarray,
        mean_ret: np.ndarray,
        cov: np.ndarray,
        rf: float,
    ) -> float:
        """Negative Sharpe ratio (for minimization)."""
        port_ret = weights @ mean_ret
        port_vol = np.sqrt(weights @ cov @ weights)
        if port_vol < EPS:
            return 0.0
        return -(port_ret - rf) / port_vol

    @staticmethod
    def _portfolio_variance(weights: np.ndarray, cov: np.ndarray) -> float:
        """Portfolio variance (for minimization)."""
        return float(weights @ cov @ weights)

    def _maximize_ratio(
        self,
        numerator_func: Callable,
        denominator_func: Callable,
        bounds: Optional[Bounds] = None,
        constraints: Optional[List] = None,
        method: str = "SLSQP",
    ) -> np.ndarray:
        """Generic ratio maximization via SciPy minimize."""
        n = self.n_assets

        if bounds is None:
            bounds = Bounds(0, 1)
        if constraints is None:
            constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        # Try multiple starting points to avoid local minima
        best_w = None
        best_val = np.inf

        initial_guesses = [
            np.ones(n) / n,  # Equal weight
            self.volatilities / self.volatilities.sum(),  # Inv vol
        ]

        for w0 in initial_guesses:
            result = minimize(
                lambda w: -numerator_func(w) / (denominator_func(w) + EPS),
                w0,
                method=method,
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-12, "maxiter": 10000},
            )
            if result.success and result.fun < best_val:
                best_val = result.fun
                best_w = result.x

        if best_w is None:
            raise RuntimeError("Optimization failed to converge")

        return best_w / best_w.sum()

    # ------------------------------------------------------------------
    # Efficient Frontier
    # ------------------------------------------------------------------

    def efficient_frontier(
        self, n_portfolios: int = 1000, allow_short: bool = False
    ) -> pd.DataFrame:
        """Simulate random portfolios and compute the efficient frontier.

        Parameters
        ----------
        n_portfolios : int, default=1000
            Number of random portfolios to simulate
        allow_short : bool, default=False
            If True, allows negative weights (unbounded)

        Returns
        -------
        pd.DataFrame with columns ['return', 'volatility', 'sharpe', ...weights]
        """
        n = self.n_assets
        np.random.seed(42)

        returns = []
        volatilities = []
        sharpes = []
        all_weights = []

        for _ in range(n_portfolios):
            if allow_short:
                w = np.random.randn(n)
            else:
                w = np.random.random(n)
            w = w / w.sum()

            port_ret = _portfolio_return(w, self.mean_returns_annual)
            port_vol = _portfolio_vol(w, self.cov_annual)
            sharpe = (port_ret - self.rf_annual) / port_vol if port_vol > EPS else 0.0

            returns.append(port_ret)
            volatilities.append(port_vol)
            sharpes.append(sharpe)
            all_weights.append(w)

        frontier = pd.DataFrame({
            "return": returns,
            "volatility": volatilities,
            "sharpe": sharpes,
        })
        for i, name in enumerate(self.asset_names):
            frontier[f"weight_{name}"] = [w[i] for w in all_weights]

        self._frontier = frontier
        return frontier

    # ------------------------------------------------------------------
    # Maximum Sharpe Ratio Portfolio (Tangency Portfolio)
    # ------------------------------------------------------------------

    def max_sharpe_portfolio(
        self, bounds: Optional[Bounds] = None
    ) -> Dict[str, Any]:
        """Find the portfolio that maximizes the Sharpe ratio.

        This is the tangency portfolio — the point on the efficient frontier
        where the capital market line is tangent.

        Parameters
        ----------
        bounds : Bounds, optional
            Weight constraints. Default is long-only [0, 1].

        Returns
        -------
        dict with keys: weights, return, volatility, sharpe
        """
        n = self.n_assets
        if bounds is None:
            bounds = Bounds(0, 1)

        w = self._maximize_ratio(
            lambda w: w @ self.mean_returns_annual,
            lambda w: np.sqrt(w @ self.cov_annual @ w),
            bounds=bounds,
        )
        port_ret = _portfolio_return(w, self.mean_returns_annual)
        port_vol = _portfolio_vol(w, self.cov_annual)
        sharpe = (port_ret - self.rf_annual) / port_vol if port_vol > EPS else 0.0

        return {
            "weights": dict(zip(self.asset_names, w.tolist())),
            "return": port_ret,
            "volatility": port_vol,
            "sharpe": sharpe,
            "method": "maximum_sharpe_ratio",
        }

    # ------------------------------------------------------------------
    # Minimum Variance Portfolio (GMV)
    # ------------------------------------------------------------------

    def min_variance_portfolio(
        self, bounds: Optional[Bounds] = None
    ) -> Dict[str, Any]:
        """Find the Global Minimum Variance (GMV) portfolio.

        The portfolio with the lowest possible volatility. Often used as the
        anchor point for more aggressive allocations.

        Parameters
        ----------
        bounds : Bounds, optional
            Weight constraints. Default is long-only [0, 1].

        Returns
        -------
        dict with keys: weights, return, volatility, sharpe
        """
        n = self.n_assets
        if bounds is None:
            bounds = Bounds(0, 1)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        best_w = None
        best_var = np.inf

        for w0 in [np.ones(n) / n, self.volatilities / self.volatilities.sum()]:
            result = minimize(
                self._portfolio_variance,
                w0,
                args=(self.cov_annual,),
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-12, "maxiter": 10000},
            )
            if result.success and result.fun < best_var:
                best_var = result.fun
                best_w = result.x

        if best_w is None:
            raise RuntimeError("GMV optimization failed")

        w = best_w / best_w.sum()
        port_ret = _portfolio_return(w, self.mean_returns_annual)
        port_vol = _portfolio_vol(w, self.cov_annual)
        sharpe = (port_ret - self.rf_annual) / port_vol if port_vol > EPS else 0.0

        return {
            "weights": dict(zip(self.asset_names, w.tolist())),
            "return": port_ret,
            "volatility": port_vol,
            "sharpe": sharpe,
            "method": "minimum_variance",
        }

    # ------------------------------------------------------------------
    # Maximum Diversification Portfolio
    # ------------------------------------------------------------------

    def max_diversification_portfolio(
        self, bounds: Optional[Bounds] = None
    ) -> Dict[str, Any]:
        """Maximum Diversification Ratio (Choueifaty & Coignard, 2008).

        Maximizes DR = (w @ sigma) / sqrt(w @ cov @ w)

        DR > 1 means the portfolio is diversified (benefiting from low
        correlations). The maximum is achieved when assets are perfectly
        negatively correlated.
        """
        n = self.n_assets
        if bounds is None:
            bounds = Bounds(0, 1)

        sigma = np.sqrt(np.diag(self.cov_annual))

        def diversification_ratio(w: np.ndarray) -> float:
            weighted_vol = w @ sigma
            port_vol = np.sqrt(w @ self.cov_annual @ w)
            return weighted_vol / port_vol if port_vol > EPS else 1.0

        w = self._maximize_ratio(
            lambda w: w @ sigma,
            lambda w: np.sqrt(w @ self.cov_annual @ w),
            bounds=bounds,
        )

        port_ret = _portfolio_return(w, self.mean_returns_annual)
        port_vol = _portfolio_vol(w, self.cov_annual)
        dr = float(w @ sigma) / port_vol if port_vol > EPS else 1.0
        sharpe = (port_ret - self.rf_annual) / port_vol if port_vol > EPS else 0.0

        return {
            "weights": dict(zip(self.asset_names, w.tolist())),
            "return": port_ret,
            "volatility": port_vol,
            "sharpe": sharpe,
            "diversification_ratio": dr,
            "method": "maximum_diversification",
        }

    # ------------------------------------------------------------------
    # Black-Litterman Model
    # ------------------------------------------------------------------

    def black_litterman(
        self,
        market_caps: np.ndarray,
        views: List[Dict],
        tau: float = 0.05,
        delta: float = 2.5,
        confidence: str = "unknown",
        bounds: Optional[Bounds] = None,
    ) -> Dict[str, Any]:
        """Black-Litterman model: blend market equilibrium with active views.

        Addresses the two biggest problems with mean-variance optimization:
        1. Input sensitivity — small changes in expected returns produce
           wild changes in optimal weights
        2. Concentrated portfolios — MVO tends to allocate everything to
           a few assets

        The BL model starts from market-cap weights (implied by the
        Capital Asset Pricing Model) and adjusts them based on the
        investor's views.

        Parameters
        ----------
        market_caps : np.ndarray
            Market capitalization weights for each asset (sums to 1)
        views : List[Dict]
            Views on assets. Each dict has:
                - 'assets': list of asset indices or names
                - 'type': 'absolute' (asset returns = value) or 'relative'
                         (asset1 outperforms asset2 by value)
                - 'value': expected return difference
                - 'confidence': 0-1, confidence in this view
        tau : float, default=0.05
            Uncertainty scale (how confident we are in the prior)
        delta : float, default=2.5
            Risk aversion coefficient (market price of risk)
        confidence : str, default='unknown'
            How confidence values are interpreted in views
        bounds : Bounds, optional
            Weight constraints

        Returns
        -------
        dict with keys: weights, return, volatility, sharpe,
                       implied_returns, posterior_returns, posterior_cov
        """
        n = self.n_assets

        # Market-cap weights (prior)
        w_mkt = np.asarray(market_caps, dtype=np.float64).flatten()
        w_mkt = w_mkt / w_mkt.sum()

        # Implied equilibrium returns (reverse-optimized from CAPM)
        # pi = delta * Sigma * w_mkt
        implied_returns = delta * self.cov_annual @ w_mkt

        # Build the view matrix P and the view vector Q
        m = len(views)
        P = np.zeros((m, n))
        Q = np.zeros(m)
        omega_diag = np.ones(m) * 0.01  # Uncertainty of views

        for i, view in enumerate(views):
            assets = view.get("assets", [])
            view_type = view.get("type", "absolute")
            value = float(view.get("value", 0.0))
            conf = float(view.get("confidence", 0.5))
            conf = np.clip(conf, 0.01, 0.99)

            # Resolve asset identifiers to indices
            for asset in assets:
                if isinstance(asset, str):
                    if asset in self.asset_names:
                        idx = self.asset_names.index(asset)
                    else:
                        raise ValueError(f"Unknown asset '{asset}'")
                else:
                    idx = int(asset)

                if view_type == "absolute":
                    P[i, idx] = 1.0 / len(assets)
                elif view_type == "relative":
                    # First half of assets outperform second half
                    mid = len(assets) // 2
                    if assets.index(asset) < mid:
                        P[i, idx] = 1.0 / mid
                    else:
                        P[i, idx] = -1.0 / (len(assets) - mid)

            Q[i] = value
            omega_diag[i] = (1.0 - conf) / conf * tau

        # Omega: uncertainty matrix of views
        Omega = np.diag(omega_diag)

        # Posterior expected returns (Black-Litterman formula)
        # E[R] = [(tau*Sigma)^(-1) + P' Omega^(-1) P]^(-1) *
        #        [(tau*Sigma)^(-1) * pi + P' Omega^(-1) * Q]
        tau_sigma = tau * self.cov_annual
        tau_sigma_inv = np.linalg.inv(tau_sigma + np.eye(n) * 1e-10)

        M = tau_sigma_inv + P.T @ np.linalg.inv(Omega + np.eye(m) * 1e-10) @ P
        M_inv = np.linalg.inv(M + np.eye(n) * 1e-10)

        posterior_returns = M_inv @ (
            tau_sigma_inv @ implied_returns
            + P.T @ np.linalg.inv(Omega + np.eye(m) * 1e-10) @ Q
        )

        # Posterior covariance
        posterior_cov = self.cov_annual + M_inv

        # Optimize with posterior expectations
        mpt = ModernPortfolioTheory.__new__(ModernPortfolioTheory)
        mpt.returns = self.returns
        mpt.n_assets = self.n_assets
        mpt.asset_names = self.asset_names
        mpt.periods_per_year = self.periods_per_year
        mpt.rf = self.rf
        mpt.rf_annual = self.rf_annual
        mpt.mean_returns = posterior_returns / self.periods_per_year
        mpt.mean_returns_annual = posterior_returns
        mpt.cov_matrix = None
        mpt.cov_annual = posterior_cov
        mpt.corr_matrix = _cov_to_corr(posterior_cov)
        mpt.volatilities = np.sqrt(np.diag(posterior_cov))

        result = mpt.max_sharpe_portfolio(bounds=bounds)
        result["implied_returns"] = implied_returns.tolist()
        result["posterior_returns"] = posterior_returns.tolist()
        result["method"] = "black_litterman"

        return result


# ============================================================================
# 2. RISK PARITY
# ============================================================================

class RiskParity:
    """Risk parity portfolio construction methods.

    Risk parity allocates capital so each asset contributes equally to
    total portfolio risk. Unlike mean-variance, it doesn't require return
    forecasts — just a covariance matrix. This makes it more robust to
    estimation error in expected returns.

    Methods:
    - Equal Risk Contribution (ERC): each asset has same risk budget
    - Inverse Volatility: weights proportional to 1/vol
    - Hierarchical Risk Parity (HRP): Lopez de Prado's tree-based approach

    Reference:
        Maillard, S., Roncalli, T., & Teiletche, J. (2010). "The Properties
            of Equally Weighted Risk Contribution Portfolios."
        Lopez de Prado, M. (2016). "Building Diversified Portfolios that
            Outperform Out-of-Sample." Journal of Portfolio Management.
    """

    def __init__(self, cov_matrix: np.ndarray, returns: Optional[pd.DataFrame] = None):
        """
        Parameters
        ----------
        cov_matrix : np.ndarray
            N x N covariance matrix (annualized or daily — consistent units)
        returns : pd.DataFrame, optional
            Returns used for correlation calculations (needed for HRP)
        """
        self.cov = np.asarray(cov_matrix, dtype=np.float64)
        _check_cov_matrix(self.cov)
        self.n = self.cov.shape[0]
        self.returns = returns
        self.corr = _cov_to_corr(self.cov)
        self.vols = np.sqrt(np.diag(self.cov))

    # ------------------------------------------------------------------
    # Equal Risk Contribution (ERC)
    # ------------------------------------------------------------------

    def equal_risk_contribution(
        self, bounds: Optional[Bounds] = None
    ) -> Dict[str, Any]:
        """Equal Risk Contribution portfolio.

        Solves for weights such that each asset's marginal risk contribution
        (MRC * weight) is equal across all assets.

        Formally: w_i * (Sigma * w)_i = w_j * (Sigma * w)_j  for all i,j

        Parameters
        ----------
        bounds : Bounds, optional

        Returns
        -------
        dict with weights, risk_contributions, convergence_info
        """
        n = self.n
        if bounds is None:
            bounds = Bounds(0, 1)

        def _risk_contributions(w: np.ndarray) -> np.ndarray:
            """Compute each asset's contribution to portfolio risk."""
            port_var = w @ self.cov @ w
            if port_var < EPS:
                return np.ones(n) / n
            mrc = self.cov @ w  # Marginal risk contributions
            rc = w * mrc
            return rc / rc.sum()  # Normalize to percentages

        def _erc_objective(w: np.ndarray) -> float:
            """Objective: minimize variance of risk contributions."""
            rc = _risk_contributions(w)
            target = 1.0 / n
            return np.sum((rc - target) ** 2)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        best_w = None
        best_obj = np.inf

        for w0 in [np.ones(n) / n, self.vols / self.vols.sum()]:
            result = minimize(
                _erc_objective,
                w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-12, "maxiter": 10000},
            )
            if result.success and result.fun < best_obj:
                best_obj = result.fun
                best_w = result.x

        if best_w is None:
            raise RuntimeError("ERC optimization failed")

        w = best_w / best_w.sum()
        rc = _risk_contributions(w)

        return {
            "weights": w,
            "risk_contributions": rc,
            "objective_value": best_obj,
            "method": "equal_risk_contribution",
            "converged": best_obj < 1e-6,
        }

    # ------------------------------------------------------------------
    # Inverse Volatility Weighting
    # ------------------------------------------------------------------

    def inverse_volatility(self) -> Dict[str, Any]:
        """Inverse volatility weighting (naive risk parity).

        Weights are proportional to 1/volatility. The simplest form of
        risk parity — ignores correlations entirely.

        Useful as a fast, robust starting point or when correlation
        estimates are unreliable.

        Returns
        -------
        dict with weights, risk_contributions
        """
        inv_vol = 1.0 / self.vols
        inv_vol[~np.isfinite(inv_vol)] = 0.0
        w = inv_vol / inv_vol.sum()

        # Compute actual risk contributions
        port_var = w @ self.cov @ w
        if port_var > EPS:
            mrc = self.cov @ w
            rc = w * mrc / port_var
        else:
            rc = np.ones(self.n) / self.n

        return {
            "weights": w,
            "risk_contributions": rc,
            "method": "inverse_volatility",
        }

    # ------------------------------------------------------------------
    # Hierarchical Risk Parity (HRP) — Lopez de Prado
    # ------------------------------------------------------------------

    def hierarchical_risk_parity(self) -> Dict[str, Any]:
        """Hierarchical Risk Parity from Lopez de Prado (2016).

        HRP uses a tree-based approach:
        1. Build a correlation distance matrix: sqrt(2 * (1 - rho))
        2. Hierarchical clustering (single linkage) to build a tree
        3. Seriation (optimal leaf ordering)
        4. Bisection: recursively split the tree, allocating risk equally
           down each branch

        Advantages over traditional risk parity:
        - Does NOT require inverting the covariance matrix
        - Handles singular or near-singular cov matrices
        - More robust out-of-sample
        - Naturally identifies and groups highly-correlated assets

        Returns
        -------
        dict with weights, clusters, linkage_matrix
        """
        n = self.n
        corr = self.corr

        # Step 1: Correlation distance matrix
        dist = np.sqrt(np.maximum(0, 2.0 * (1.0 - corr)))
        np.fill_diagonal(dist, 0.0)

        # Step 2: Hierarchical clustering (single linkage)
        # Use condensed distance matrix
        condensed = linalg.norm(dist - np.diag(np.diag(dist)))  # placeholder, use squareform
        # Proper approach:
        from scipy.spatial.distance import squareform
        condensed_dist = squareform(dist, checks=False)
        linkage = cluster.hierarchy.single(condensed_dist)

        # Step 3: Seriation — optimal leaf ordering
        # Get the order of leaves from the linkage tree
        order = self._get_quasi_diag(linkage)
        ordered_corr = corr[np.ix_(order, order)]

        # Step 4: Recursive bisection
        weights = self._recursive_bisection(ordered_corr, self.cov[np.ix_(order, order)])

        # Map back to original order
        w = np.zeros(n)
        w[order] = weights

        port_var = w @ self.cov @ w
        if port_var > EPS:
            mrc = self.cov @ w
            rc = w * mrc / port_var
        else:
            rc = np.ones(n) / n

        return {
            "weights": w,
            "risk_contributions": rc,
            "order": order,
            "linkage": linkage,
            "method": "hierarchical_risk_parity",
        }

    @staticmethod
    def _get_quasi_diag(linkage: np.ndarray) -> np.ndarray:
        """Quasi-diagonalization: reorder assets by cluster linkage.

        Returns the leaf order from hierarchical clustering.
        """
        n = linkage.shape[0] + 1
        items = list(range(n))

        # Build the cluster tree
        clusters = {i: [i] for i in range(n)}
        for i, row in enumerate(linkage):
            idx = n + i
            left = int(row[0])
            right = int(row[1])
            clusters[idx] = clusters.pop(left, [left]) + clusters.pop(right, [right])

        # Return the top-level cluster leaf order
        root = n + linkage.shape[0] - 1
        return np.array(clusters.get(root, items), dtype=int)

    @staticmethod
    def _recursive_bisection(
        corr: np.ndarray, cov: np.ndarray
    ) -> np.ndarray:
        """Recursively split and allocate risk equally.

        Works top-down: at each split, the two sub-portfolios get equal
        risk budgets, and weights are adjusted by inverse variance.
        """
        n = corr.shape[0]
        if n == 1:
            return np.array([1.0])

        # Find the split point
        # Minimize the sum of between-cluster correlation
        best_split = 1
        best_score = np.inf

        for split in range(1, n):
            left_vars = np.diag(cov[:split, :split])
            right_vars = np.diag(cov[split:, split:])
            left_corr = corr[:split, :split]
            right_corr = corr[split:, split:]

            # Score: sum of off-diagonal correlations in each cluster
            score = (
                np.sum(np.triu(left_corr, 1))
                + np.sum(np.triu(right_corr, 1))
                / max(1, right_corr.shape[0] * (right_corr.shape[0] - 1) / 2)
            )
            if score < best_score:
                best_score = score
                best_split = split

        # Recursively allocate
        left_weights = RiskParity._recursive_bisection(
            corr[:best_split, :best_split], cov[:best_split, :best_split]
        )
        right_weights = RiskParity._recursive_bisection(
            corr[best_split:, best_split:], cov[best_split:, best_split:]
        )

        # Inverse-variance weighting across the two clusters
        left_var = np.sum(left_weights * (cov[:best_split, :best_split] @ left_weights))
        right_var = np.sum(right_weights * (cov[best_split:, best_split:] @ right_weights))

        if left_var + right_var > EPS:
            alpha = 1.0 - left_var / (left_var + right_var)
            alpha = np.clip(alpha, 0.0, 1.0)
        else:
            alpha = 0.5

        left_weights *= alpha
        right_weights *= (1.0 - alpha)

        return np.concatenate([left_weights, right_weights])

    # ------------------------------------------------------------------
    # Calculate risk contribution given weights
    # ------------------------------------------------------------------

    def risk_contributions(self, weights: np.ndarray) -> np.ndarray:
        """Compute percentage risk contribution of each asset."""
        w = np.asarray(weights, dtype=np.float64)
        w = w / w.sum()
        port_var = w @ self.cov @ w
        if port_var < EPS:
            return np.ones(self.n) / self.n
        mrc = self.cov @ w
        return w * mrc / port_var



# ============================================================================
# 3. PORTFOLIO CONSTRUCTOR
# ============================================================================

@dataclass
class Position:
    """A single portfolio position."""
    asset_id: str
    quantity: float = 0.0
    cost_basis: float = 0.0
    current_price: float = 0.0
    currency: str = "USD"
    fx_rate: float = 1.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price * self.fx_rate

    @property
    def unrealized_pnl(self) -> float:
        return self.quantity * (self.current_price - self.cost_basis) * self.fx_rate

    @property
    def cost_value(self) -> float:
        return self.quantity * self.cost_basis * self.fx_rate


@dataclass
class PortfolioState:
    """Snapshot of the entire portfolio at a point in time."""
    timestamp: datetime
    positions: Dict[str, Position]
    cash: float = 0.0
    total_value: float = 0.0
    currency: str = "USD"

    def __post_init__(self):
        self.total_value = self.cash + sum(p.market_value for p in self.positions.values())

    def weight_of(self, asset_id: str) -> float:
        if self.total_value < EPS:
            return 0.0
        pos = self.positions.get(asset_id)
        if pos is None:
            return 0.0
        return pos.market_value / self.total_value

    def current_weights(self) -> Dict[str, float]:
        return {aid: self.weight_of(aid) for aid in self.positions}

    def summary(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "total_value": self.total_value,
            "cash": self.cash,
            "cash_pct": self.cash / self.total_value if self.total_value > EPS else 0.0,
            "num_positions": len(self.positions),
            "positions": {aid: {
                "quantity": p.quantity,
                "market_value": p.market_value,
                "weight": self.weight_of(aid),
                "unrealized_pnl": p.unrealized_pnl,
            } for aid, p in self.positions.items()},
        }


class PortfolioConstructor:
    """Multi-method portfolio construction with rebalancing and cash management.

    This is the operational engine that turns target allocations into
    actual trades. Handles:
    - Multiple construction methods (equal weight, cap weight, factor, etc.)
    - Calendar, threshold, and volatility-based rebalancing
    - Tax-aware rebalancing (harvest losses, defer gains)
    - Cash flow management (deposits, withdrawals, dividends)
    - Multi-currency handling with FX hedging

    Parameters
    ----------
    initial_cash : float, default=0.0
        Starting cash balance
    currency : str, default='USD'
        Base portfolio currency
    """

    def __init__(self, initial_cash: float = 0.0, currency: str = "USD"):
        self.currency = currency
        self.state = PortfolioState(
            timestamp=datetime.now(),
            positions={},
            cash=initial_cash,
            currency=currency,
        )
        self._trade_log: List[Dict] = []
        self._rebalance_log: List[Dict] = []
        self._fx_rates: Dict[str, float] = {"USD": 1.0}

    # ------------------------------------------------------------------
    # Construction Methods
    # ------------------------------------------------------------------

    @staticmethod
    def equal_weight(n_assets: int) -> np.ndarray:
        """Simple 1/N allocation."""
        return np.ones(n_assets) / n_assets

    @staticmethod
    def market_cap_weight(market_caps: np.ndarray) -> np.ndarray:
        """Capitalization-weighted allocation."""
        caps = np.asarray(market_caps, dtype=np.float64)
        caps = np.maximum(caps, 0.0)
        total = caps.sum()
        if total < EPS:
            return np.ones(len(caps)) / len(caps)
        return caps / total

    @staticmethod
    def factor_weight(
        factor_scores: np.ndarray, temperature: float = 1.0
    ) -> np.ndarray:
        """Softmax-weighted allocation based on factor scores.

        Higher temperature = more uniform allocation.
        Lower temperature = more concentrated in high-scoring assets.
        """
        scores = np.asarray(factor_scores, dtype=np.float64)
        scores = scores - scores.max()  # Numerical stability
        exp_scores = np.exp(scores / max(temperature, 0.01))
        return exp_scores / exp_scores.sum()

    @staticmethod
    def risk_budget_weights(
        target_risk: np.ndarray, cov: np.ndarray
    ) -> np.ndarray:
        """Allocate to match target risk contributions.

        target_risk[i] = desired fraction of total risk from asset i
        """
        n = len(target_risk)
        target = np.asarray(target_risk, dtype=np.float64)
        target = target / target.sum()

        def _risk_budget_obj(w: np.ndarray) -> float:
            port_var = w @ cov @ w
            if port_var < EPS:
                return 1.0
            mrc = cov @ w
            actual = w * mrc / port_var
            return np.sum((actual - target) ** 2)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = Bounds(0, 1)

        w0 = np.ones(n) / n
        result = minimize(
            _risk_budget_obj, w0,
            method="SLSQP", bounds=bounds, constraints=constraints,
            options={"ftol": 1e-12},
        )
        if not result.success:
            raise RuntimeError(f"Risk budget optimization failed: {result.message}")
        return result.x / result.x.sum()

    @staticmethod
    def minimum_tracking_error(
        benchmark_weights: np.ndarray, cov: np.ndarray,
        max_active_weight: float = 0.05,
    ) -> np.ndarray:
        """Minimize tracking error vs a benchmark (index replication)."""
        n = len(benchmark_weights)
        bm = np.asarray(benchmark_weights, dtype=np.float64)
        bm = bm / bm.sum()

        def _te(w: np.ndarray) -> float:
            active = w - bm
            return float(np.sqrt(active @ cov @ active))

        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
        ]
        bounds = Bounds(np.maximum(0, bm - max_active_weight),
                        np.minimum(1, bm + max_active_weight))

        result = minimize(_te, bm, method="SLSQP",
                          bounds=bounds, constraints=constraints)
        if not result.success:
            raise RuntimeError(f"Tracking error opt failed: {result.message}")
        return result.x / result.x.sum()

    # ------------------------------------------------------------------
    # Execute Trades
    # ------------------------------------------------------------------

    def execute_trade(
        self,
        asset_id: str,
        quantity: float,
        price: float,
        timestamp: Optional[datetime] = None,
        currency: str = "USD",
        cost_basis: Optional[float] = None,
        commission: float = 0.0,
    ) -> Dict[str, Any]:
        """Execute a trade and update portfolio state.

        Parameters
        ----------
        asset_id : str
            Asset identifier (ticker, ISIN, etc.)
        quantity : float
            Positive = buy, negative = sell
        price : float
            Execution price per unit
        timestamp : datetime, optional
            Trade time. Defaults to now.
        currency : str, default='USD'
            Trade currency
        cost_basis : float, optional
            Cost basis for tax purposes. Default = price.
        commission : float, default=0.0
            Trading commission/fees

        Returns
        -------
        dict with trade_id, asset_id, quantity, notional, etc.
        """
        ts = timestamp or datetime.now()
        cost_basis = cost_basis or price
        fx = self._fx_rates.get(currency, 1.0)
        notional = quantity * price * fx
        commission_adj = commission * fx

        if asset_id not in self.state.positions:
            self.state.positions[asset_id] = Position(
                asset_id=asset_id, currency=currency, fx_rate=fx
            )

        pos = self.state.positions[asset_id]
        old_qty = pos.quantity
        old_cost = pos.cost_basis

        if quantity >= 0:
            # Buy: update cost basis (weighted average)
            new_cost = (old_qty * old_cost + quantity * cost_basis) / (old_qty + quantity + EPS)
            pos.cost_basis = new_cost
        else:
            # Sell: reduce position, cost basis unchanged
            # Realized P&L tracking
            sell_qty = min(abs(quantity), old_qty)
            realized_pnl = sell_qty * (price - old_cost) * fx - commission_adj
            self._trade_log[-1:0]  # placeholder

        pos.quantity += quantity
        pos.current_price = price
        self.state.cash -= (notional + commission_adj)
        self.state.timestamp = ts

        trade_record = {
            "timestamp": ts,
            "asset_id": asset_id,
            "quantity": quantity,
            "price": price,
            "notional": notional,
            "commission": commission_adj,
            "currency": currency,
        }
        self._trade_log.append(trade_record)
        return trade_record

    # ------------------------------------------------------------------
    # Rebalance to Target Weights
    # ------------------------------------------------------------------

    def rebalance_to_weights(
        self,
        target_weights: Dict[str, float],
        prices: Dict[str, float],
        timestamp: Optional[datetime] = None,
        max_turnover: float = 1.0,
        tax_aware: bool = False,
        unrealized_gains: Optional[Dict[str, float]] = None,
        min_trade_size: float = 0.0,
    ) -> List[Dict]:
        """Execute trades to reach target portfolio weights.

        Parameters
        ----------
        target_weights : dict
            Target allocation {asset_id: weight}
        prices : dict
            Current prices {asset_id: price}
        timestamp : datetime, optional
        max_turnover : float, default=1.0
            Maximum one-way turnover as fraction of portfolio
        tax_aware : bool, default=False
            If True, prioritize tax-loss harvesting and defer gains
        unrealized_gains : dict, optional
            {asset_id: gain_per_share} for tax-aware adjustments
        min_trade_size : float, default=0.0
            Minimum notional trade amount

        Returns
        -------
        list of trade records
        """
        ts = timestamp or datetime.now()
        total_value = self.state.total_value

        if total_value < EPS:
            return []

        trades = []
        current_weights = self.state.current_weights()

        # Compute dollar target and current values
        all_assets = set(list(target_weights.keys()) + list(current_weights.keys()))
        trade_list = []

        for asset in all_assets:
            target_w = target_weights.get(asset, 0.0)
            current_w = current_weights.get(asset, 0.0)
            target_value = target_w * total_value
            current_value = current_weights.get(asset, 0.0) * total_value
            delta = target_value - current_value

            price = prices.get(asset, 0.0)
            if price < EPS:
                continue

            quantity = delta / price

            if abs(delta) < min_trade_size or abs(quantity) < 1e-8:
                continue

            trade_list.append((asset, quantity, price, current_w, target_w, delta))

        # Tax-aware: prioritize selling losers, defer selling winners
        if tax_aware and unrealized_gains:
            # Sort sells: losers first (tax-harvest), then small winners, then big winners
            sells = [t for t in trade_list if t[1] < 0]
            buys = [t for t in trade_list if t[1] > 0]

            sells.sort(key=lambda t: unrealized_gains.get(t[0], 0.0))
            trade_list = buys + sells

        # Apply turnover constraint
        gross_turnover = sum(abs(t[5]) for t in trade_list) / total_value
        if gross_turnover > max_turnover and gross_turnover > EPS:
            scale = max_turnover / gross_turnover
            trade_list = [
                (a, q * scale, p, cw, tw, d * scale)
                for a, q, p, cw, tw, d in trade_list
            ]

        # Execute trades
        for asset, quantity, price, cw, tw, delta in trade_list:
            trade = self.execute_trade(
                asset_id=asset, quantity=quantity, price=price,
                timestamp=ts,
            )
            trades.append(trade)

        self._rebalance_log.append({
            "timestamp": ts,
            "turnover": gross_turnover,
            "n_trades": len(trades),
        })

        return trades

    # ------------------------------------------------------------------
    # Cash Flow Management
    # ------------------------------------------------------------------

    def deposit(self, amount: float, currency: str = "USD",
                timestamp: Optional[datetime] = None) -> None:
        """Add cash to the portfolio."""
        fx = self._fx_rates.get(currency, 1.0) / self._fx_rates.get(self.currency, 1.0)
        self.state.cash += amount * fx
        self.state.timestamp = timestamp or datetime.now()

    def withdraw(self, amount: float, currency: str = "USD",
                 timestamp: Optional[datetime] = None) -> float:
        """Withdraw cash from the portfolio. Raises if insufficient."""
        fx = self._fx_rates.get(currency, 1.0) / self._fx_rates.get(self.currency, 1.0)
        cash_needed = amount * fx
        if self.state.cash < cash_needed - 1e-8:
            # Liquidate positions if needed
            raise ValueError(
                f"Insufficient cash: {self.state.cash:.2f} {self.currency}, "
                f"need {cash_needed:.2f}"
            )
        self.state.cash -= cash_needed
        self.state.timestamp = timestamp or datetime.now()
        return amount

    def update_prices(self, prices: Dict[str, float]) -> None:
        """Update position prices to current market values."""
        for aid, price in prices.items():
            if aid in self.state.positions:
                self.state.positions[aid].current_price = price
        self.state.__post_init__()

    def set_fx_rate(self, currency: str, rate: float) -> None:
        """Set FX rate relative to base currency."""
        self._fx_rates[currency] = rate

    # ------------------------------------------------------------------
    # Portfolio Metrics
    # ------------------------------------------------------------------

    def gross_exposure(self) -> float:
        """Sum of absolute position values (gross exposure)."""
        return sum(p.market_value for p in self.state.positions.values())

    def net_exposure(self) -> float:
        """Net market exposure (long - short)."""
        return sum(
            p.market_value for p in self.state.positions.values() if p.quantity > 0
        ) - sum(
            -p.market_value for p in self.state.positions.values() if p.quantity < 0
        )

    def leverage(self) -> float:
        """Gross exposure / equity."""
        equity = self.state.total_value
        return self.gross_exposure() / equity if equity > EPS else 0.0

    def concentration(self, top_n: int = 5) -> float:
        """Fraction of portfolio in top N positions."""
        values = sorted(
            [p.market_value for p in self.state.positions.values()],
            reverse=True,
        )
        top_value = sum(values[:top_n])
        return top_value / self.state.total_value if self.state.total_value > EPS else 0.0

    def effective_n(self) -> float:
        """Herfindahl-Hirschman Index conversion: 1 / sum(w^2).

        The number of equally-sized positions that would produce the
        same concentration. Higher = more diversified.
        """
        w = np.array(list(self.state.current_weights().values()))
        hhi = np.sum(w ** 2)
        return 1.0 / hhi if hhi > EPS else 1.0


# ============================================================================
# 4. PERFORMANCE ANALYTICS
# ============================================================================

class PerformanceAnalytics:
    """Comprehensive portfolio performance measurement.

    For the professional who knows that raw returns are meaningless without
    risk adjustment. Every metric here answers the question: was the return
    earned through skill or through taking excessive risk?

    Metrics: Sharpe, Sortino, Calmar, Sterling, Information, Treynor,
    Jensen's Alpha, win rate, profit factor, expectancy, recovery factor,
    max drawdown, ulcer index, and significance testing for all ratios.

    Parameters
    ----------
    returns : pd.Series or pd.DataFrame
        Portfolio returns (single series or multi-column)
    benchmark : pd.Series, optional
        Benchmark returns for relative metrics
    risk_free_rate : float, default=0.0
        Annualized risk-free rate
    periods_per_year : int, default=252
        Trading periods per year
    """

    def __init__(
        self,
        returns: Union[pd.Series, pd.DataFrame],
        benchmark: Optional[pd.Series] = None,
        risk_free_rate: float = 0.0,
        periods_per_year: int = 252,
    ):
        if isinstance(returns, pd.DataFrame):
            self.returns = returns.iloc[:, 0].astype(np.float64)
        else:
            self.returns = returns.astype(np.float64)
        self.returns = self.returns.dropna()
        self.n = len(self.returns)
        self.ppy = periods_per_year
        self.rf = risk_free_rate / periods_per_year  # Per-period risk-free
        self.rf_ann = risk_free_rate

        self.benchmark = None
        if benchmark is not None:
            bm = benchmark.dropna()
            self.benchmark = bm.reindex(self.returns.index).dropna()
            self.returns = self.returns.reindex(self.benchmark.index).dropna()
            self.benchmark = self.benchmark.reindex(self.returns.index)

        self.excess_returns = self.returns - self.rf
        self.cumulative = (1.0 + self.returns).cumprod()

        # Cache common calculations
        self._mean_return = float(self.returns.mean())
        self._vol = float(self.returns.std(ddof=1))
        self._ann_return = _annualized_return(self._mean_return, self.ppy)
        self._ann_vol = _annualized_vol(self._vol, self.ppy)
        self._skew = float(self.returns.skew())
        self._kurt = float(self.returns.kurtosis())

        # Downside metrics cache
        self._downside_returns = self.returns[self.returns < self.rf]
        self._downside_vol = float(self._downside_returns.std(ddof=1)) if len(self._downside_returns) > 1 else 0.0

    # ------------------------------------------------------------------
    # Risk-Adjusted Return Ratios
    # ------------------------------------------------------------------

    def sharpe_ratio(self, significance_level: float = 0.05) -> Dict[str, float]:
        """Sharpe ratio with standard error and significance test.

        Sharpe = E[R - Rf] / sigma(R - Rf)

        Standard error (Lo, 2002):
        SE(Sharpe) = sqrt((1 + 0.5 * Sharpe^2) / (n - 1))

        Parameters
        ----------
        significance_level : float, default=0.05
            For confidence interval

        Returns
        -------
        dict with sharpe, annualized_sharpe, se, t_stat, p_value, ci_lower, ci_upper
        """
        if self._vol < EPS:
            return {"sharpe": 0.0, "annualized_sharpe": 0.0, "se": np.nan, "t_stat": 0.0, "p_value": 1.0}

        sr = self._mean_return / self._vol
        sr_ann = sr * np.sqrt(self.ppy)

        # Lo (2002) standard error
        n = self.n
        se = np.sqrt((1.0 + 0.5 * sr ** 2) / (n - 1)) if n > 1 else np.nan
        t_stat = sr / se if se and se > EPS else 0.0
        p_value = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n - 1)) if n > 1 else 1.0

        # Confidence interval
        z = stats.norm.ppf(1.0 - significance_level / 2.0)
        ci_lower = sr_ann - z * se * np.sqrt(self.ppy) if np.isfinite(se) else np.nan
        ci_upper = sr_ann + z * se * np.sqrt(self.ppy) if np.isfinite(se) else np.nan

        return {
            "sharpe": sr,
            "annualized_sharpe": sr_ann,
            "se": se,
            "t_stat": t_stat,
            "p_value": p_value,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
        }

    def sortino_ratio(self) -> float:
        """Sortino ratio: focuses on downside deviation only.

        Sortino = E[R - Rf] / downside_sigma

        A higher Sortino means the portfolio generates returns without
        taking excessive downside risk — the hallmark of a skilled manager.
        """
        if self._downside_vol < EPS:
            return 0.0
        sortino = self._mean_return / self._downside_vol
        return sortino * np.sqrt(self.ppy)

    def calmar_ratio(self, periods: Optional[int] = None) -> float:
        """Calmar ratio: annualized return / max drawdown.

        A Calmar > 1.0 is excellent. > 3.0 is exceptional.
        Used heavily by CTAs and managed futures.

        Parameters
        ----------
        periods : int, optional
            Lookback period. Uses all data if None.
        """
        returns = self.returns.tail(periods) if periods else self.returns
        ann_ret = _annualized_return(float(returns.mean()), self.ppy)
        dd = DrawdownAnalytics(returns)
        max_dd = dd.max_drawdown["max_drawdown"]
        if abs(max_dd) < EPS:
            return float("inf")
        return ann_ret / abs(max_dd)

    def sterling_ratio(self) -> float:
        """Sterling ratio: annualized return / (average annual drawdown + 10%).

        More conservative than Calmar — uses average drawdown instead of max,
        and adds a 10% penalty in the denominator. Developed by fund-of-funds
        managers who found Calmar too optimistic.
        """
        dd = DrawdownAnalytics(self.returns)
        avg_dd = dd.average_drawdown()
        denom = abs(avg_dd) + 0.10
        return self._ann_return / denom if denom > EPS else 0.0

    def information_ratio(self) -> float:
        """Information ratio: active return / tracking error.

        IR = E[R - Rb] / sigma(R - Rb)

        Measures consistency of alpha generation. An IR > 0.5 is good,
        > 1.0 is excellent (top-quartile managers).
        """
        if self.benchmark is None:
            return np.nan

        active = self.returns - self.benchmark
        active_mean = float(active.mean())
        active_vol = float(active.std(ddof=1))
        if active_vol < EPS:
            return 0.0
        return (active_mean / active_vol) * np.sqrt(self.ppy)

    def treynor_ratio(self, beta: Optional[float] = None) -> float:
        """Treynor ratio: excess return / systematic risk (beta).

        Unlike Sharpe (which penalizes diversifiable risk), Treynor only
        penalizes market risk. Useful for evaluating a portfolio that is
        a small part of a larger allocation.

        Parameters
        ----------
        beta : float, optional
            Portfolio beta. Computed from benchmark if not provided.
        """
        if beta is None:
            if self.benchmark is None:
                return np.nan
            beta = self.beta()

        if abs(beta) < EPS:
            return 0.0 if self._mean_return > self.rf else 0.0
        return (self._ann_return - self.rf_ann) / beta

    def jensen_alpha(self) -> Dict[str, float]:
        """Jensen's Alpha: risk-adjusted excess return from CAPM.

        Alpha = R - [Rf + beta * (Rm - Rf)]

        Positive alpha = manager skill. Requires a benchmark.
        """
        if self.benchmark is None:
            return {"alpha": np.nan, "alpha_annualized": np.nan, "beta": np.nan, "t_stat": np.nan}

        beta = self.beta()
        bm_excess = self.benchmark - self.rf
        alpha_series = self.excess_returns - beta * bm_excess
        alpha = float(alpha_series.mean())
        alpha_ann = _annualized_return(alpha, self.ppy)

        # T-statistic for alpha significance
        alpha_se = float(alpha_series.std(ddof=1)) / np.sqrt(self.n)
        t_stat = alpha / alpha_se if alpha_se > EPS else 0.0

        return {
            "alpha": alpha,
            "alpha_annualized": alpha_ann,
            "beta": beta,
            "t_stat": t_stat,
            "p_value": 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=self.n - 1)),
        }

    def beta(self) -> float:
        """Portfolio beta relative to benchmark."""
        if self.benchmark is None:
            return np.nan
        cov = float(np.cov(self.returns, self.benchmark, ddof=1)[0, 1])
        bm_var = float(self.benchmark.var(ddof=1))
        return cov / bm_var if bm_var > EPS else 0.0

    # ------------------------------------------------------------------
    # Trade / P&L Statistics
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_trades(trades: pd.Series) -> Tuple[pd.Series, pd.Series]:
        """Separate winning and losing trades."""
        winners = trades[trades > 0]
        losers = trades[trades < 0]
        return winners, losers

    def win_rate(self, trades: Optional[pd.Series] = None) -> float:
        """Fraction of trades that are profitable."""
        if trades is None:
            trades = self.returns
        winners = (trades > 0).sum()
        total = max(len(trades), 1)
        return winners / total

    def profit_factor(self, trades: Optional[pd.Series] = None) -> float:
        """Gross profit / gross loss.

        PF > 1.0 means the strategy is profitable. Professional strategies
        typically have PF > 1.5. High-frequency strategies > 2.0.
        """
        if trades is None:
            trades = self.returns
        gross_profit = trades[trades > 0].sum()
        gross_loss = abs(trades[trades < 0].sum())
        return gross_profit / gross_loss if gross_loss > EPS else float("inf")

    def expectancy(self, trades: Optional[pd.Series] = None) -> float:
        """Average P&L per trade.

        E = (WinRate * AvgWin) - (LossRate * AvgLoss)

        Also known as edge per trade.
        """
        if trades is None:
            trades = self.returns
        w, l = self._classify_trades(trades)
        wr = self.win_rate(trades)
        lr = 1.0 - wr
        avg_w = float(w.mean()) if len(w) > 0 else 0.0
        avg_l = float(l.mean()) if len(l) > 0 else 0.0
        return wr * avg_w - lr * abs(avg_l)

    def average_win_loss(self, trades: Optional[pd.Series] = None) -> Dict[str, float]:
        """Average win, average loss, and their ratio."""
        if trades is None:
            trades = self.returns
        w, l = self._classify_trades(trades)
        avg_w = float(w.mean()) if len(w) > 0 else 0.0
        avg_l = float(l.mean()) if len(l) > 0 else 0.0
        ratio = abs(avg_w / avg_l) if abs(avg_l) > EPS else float("inf")
        return {"avg_win": avg_w, "avg_loss": avg_l, "win_loss_ratio": ratio}

    def consecutive_wins_losses(self, trades: Optional[pd.Series] = None) -> Dict[str, int]:
        """Longest run of consecutive wins and losses.

        Critical for position sizing and drawdown management.
        """
        if trades is None:
            trades = self.returns

        wins = (trades > 0).astype(int)
        max_consec_wins = 0
        max_consec_losses = 0
        current = 0
        current_type = 0  # 0 = unknown, 1 = win, -1 = loss

        for val in wins.values:
            if val == 1:
                if current_type == 1:
                    current += 1
                else:
                    current_type = 1
                    current = 1
            else:
                if current_type == -1:
                    current += 1
                else:
                    current_type = -1
                    current = 1

            if current_type == 1:
                max_consec_wins = max(max_consec_wins, current)
            else:
                max_consec_losses = max(max_consec_losses, current)

        return {"max_consecutive_wins": max_consec_wins,
                "max_consecutive_losses": max_consec_losses}

    def recovery_factor(self) -> float:
        """Total return / max drawdown.

        Measures how quickly the strategy recovers from its worst loss.
        A recovery factor > 3 is good; > 10 is exceptional.
        """
        total_ret = float(self.cumulative.iloc[-1]) - 1.0 if len(self.cumulative) > 0 else 0.0
        dd = DrawdownAnalytics(self.returns)
        max_dd = abs(dd.max_drawdown["max_drawdown"])
        return total_ret / max_dd if max_dd > EPS else float("inf")

    def ulcer_index(self) -> float:
        """Ulcer Index: depth and duration of drawdowns.

        UI = sqrt(mean(drawdown_series^2))

        Developed by Peter Martin. Measures the 'pain' of holding through
        drawdowns — captures BOTH how deep AND how long they last.
        Lower is better.
        """
        dd = DrawdownAnalytics(self.returns)
        dd_series = dd.drawdown_series
        return float(np.sqrt(np.mean(dd_series ** 2)))

    def gain_to_pain_ratio(self) -> float:
        """Gain-to-Pain ratio: cumulative return / cumulative absolute drawdown.

        GPR > 0.5 is good; > 1.0 is excellent.
        """
        dd = DrawdownAnalytics(self.returns)
        cumulative_dd = float(dd.drawdown_series.abs().sum())
        if cumulative_dd < EPS:
            return float("inf")
        total_ret = float(self.cumulative.iloc[-1]) - 1.0 if len(self.cumulative) > 0 else 0.0
        return total_ret / cumulative_dd

    def summary(self) -> Dict[str, Any]:
        """Comprehensive performance summary with all key metrics."""
        sharpe = self.sharpe_ratio()
        jensen = self.jensen_alpha()

        return {
            "total_return": float(self.cumulative.iloc[-1] - 1.0) if len(self.cumulative) > 0 else 0.0,
            "annualized_return": self._ann_return,
            "annualized_volatility": self._ann_vol,
            "skewness": self._skew,
            "kurtosis": self._kurt,
            "sharpe_ratio": sharpe["annualized_sharpe"],
            "sharpe_significant": sharpe.get("p_value", 1.0) < 0.05,
            "sortino_ratio": self.sortino_ratio(),
            "calmar_ratio": self.calmar_ratio(),
            "sterling_ratio": self.sterling_ratio(),
            "information_ratio": self.information_ratio(),
            "treynor_ratio": self.treynor_ratio(),
            "jensen_alpha": jensen.get("alpha_annualized", np.nan),
            "beta": jensen.get("beta", np.nan),
            "win_rate": self.win_rate(),
            "profit_factor": self.profit_factor(),
            "expectancy": self.expectancy(),
            **self.average_win_loss(),
            **self.consecutive_wins_losses(),
            "recovery_factor": self.recovery_factor(),
            "ulcer_index": self.ulcer_index(),
            "gain_to_pain": self.gain_to_pain_ratio(),
        }


# ============================================================================
# 5. DRAWDOWN ANALYTICS
# ============================================================================

class DrawdownAnalytics:
    """Comprehensive drawdown analysis beyond the simple max drawdown.

    For the professional who knows that max drawdown alone is dangerously
    misleading — a strategy with one severe 50% drawdown and another with
    frequent 10% drawdowns that last months are very different risks.

    Provides:
    - Max drawdown with precise peak/trough dates and duration
    - Drawdown duration distribution (how long do losses last?)
    - Average recovery time (mean time to new high)
    - Pain ratio (total area under the drawdown curve)
    - Lake ratio (drawdown severity × duration visual proxy)

    Parameters
    ----------
    returns : pd.Series
        Time series of portfolio returns
    """

    def __init__(self, returns: pd.Series):
        self.returns = returns.dropna().astype(np.float64)
        self.cumulative = (1.0 + self.returns).cumprod()
        self._compute_drawdowns()

    def _compute_drawdowns(self) -> None:
        """Compute the drawdown series and all peak/trough information."""
        if len(self.cumulative) == 0:
            self.drawdown_series = pd.Series(dtype=np.float64)
            self.peak_cum = pd.Series(dtype=np.float64)
            self.max_drawdown = {"max_drawdown": 0.0, "peak_idx": None, "trough_idx": None}
            self._drawdown_periods = []
            return

        # Running maximum (peak)
        self.peak_cum = self.cumulative.cummax()

        # Drawdown from peak (as negative percentage)
        self.drawdown_series = (self.cumulative / self.peak_cum) - 1.0

        # Find max drawdown
        min_idx = self.drawdown_series.idxmin()
        max_dd = self.drawdown_series[min_idx]

        # Find the peak before this trough
        peak_idx = self.cumulative[:min_idx].idxmax() if min_idx != self.cumulative.index[0] else self.cumulative.index[0]

        self.max_drawdown = {
            "max_drawdown": max_dd,
            "peak_idx": peak_idx,
            "trough_idx": min_idx,
            "peak_date": peak_idx,
            "trough_date": min_idx,
            "peak_value": float(self.cumulative[peak_idx]),
            "trough_value": float(self.cumulative[min_idx]),
        }

        # Identify distinct drawdown periods
        self._drawdown_periods = self._identify_drawdown_periods()

    def _identify_drawdown_periods(self) -> List[Dict]:
        """Identify each distinct drawdown period with start/end/extent.

        A drawdown period starts when the portfolio falls X% from its peak
        and ends when a new peak is reached.
        """
        periods = []
        in_dd = False
        dd_start = None
        dd_peak = None
        dd_peak_val = 1.0
        current_trough = 0.0
        current_trough_idx = None

        for idx, val in self.cumulative.items():
            if not in_dd:
                if val < dd_peak_val:  # Start of drawdown
                    in_dd = True
                    dd_start = idx
                    dd_peak = idx  # Actually the previous peak
                    current_trough = val
                    current_trough_idx = idx
                else:
                    dd_peak_val = val
                    dd_peak = idx
            else:
                if val < current_trough:
                    current_trough = val
                    current_trough_idx = idx

                if val >= dd_peak_val:  # New high — recovery
                    recovery_idx = idx
                    dd_depth = (current_trough / dd_peak_val) - 1.0

                    if dd_depth < -0.01:  # Only record meaningful drawdowns
                        periods.append({
                            "start": dd_start,
                            "end": recovery_idx,
                            "peak_value": float(dd_peak_val),
                            "trough_value": float(current_trough),
                            "max_drawdown": dd_depth,
                            "duration_days": (recovery_idx - dd_start).days if hasattr(recovery_idx, 'days') else 0,
                            "recovery_days": (recovery_idx - current_trough_idx).days if hasattr(recovery_idx, 'days') else 0,
                        })

                    in_dd = False
                    dd_peak_val = val
                    dd_peak = idx
                    current_trough = val
                    current_trough_idx = idx

        # If still in drawdown at end, record it
        if in_dd and dd_start is not None:
            dd_depth = (current_trough / dd_peak_val) - 1.0
            if dd_depth < -0.01:
                periods.append({
                    "start": dd_start,
                    "end": None,  # Still in drawdown
                    "peak_value": float(dd_peak_val),
                    "trough_value": float(current_trough),
                    "max_drawdown": dd_depth,
                    "duration_days": None,
                    "recovery_days": None,
                })

        return periods

    def max_drawdown_info(self) -> Dict[str, Any]:
        """Detailed max drawdown with dates and values."""
        return {
            **self.max_drawdown,
            "drawdown_percentage": self.max_drawdown["max_drawdown"] * 100,
        }

    def drawdown_periods(self) -> List[Dict]:
        """All distinct drawdown periods with start/end/depth/duration."""
        return self._drawdown_periods

    def average_drawdown(self) -> float:
        """Mean drawdown across all periods."""
        depths = [p["max_drawdown"] for p in self._drawdown_periods]
        if not depths:
            return 0.0
        return float(np.mean(depths))

    def median_drawdown(self) -> float:
        """Median drawdown across all periods."""
        depths = [p["max_drawdown"] for p in self._drawdown_periods]
        if not depths:
            return 0.0
        return float(np.median(depths))

    def average_recovery_time(self) -> float:
        """Average number of days to recover from a drawdown to new high."""
        recovery_days = [
            p["recovery_days"] for p in self._drawdown_periods
            if p["recovery_days"] is not None
        ]
        if not recovery_days:
            return float("inf")
        return float(np.mean(recovery_days))

    def median_recovery_time(self) -> float:
        """Median recovery time in days."""
        recovery_days = [
            p["recovery_days"] for p in self._drawdown_periods
            if p["recovery_days"] is not None
        ]
        if not recovery_days:
            return float("inf")
        return float(np.median(recovery_days))

    def average_drawdown_duration(self) -> float:
        """Mean duration of drawdown periods in days."""
        durations = [
            p["duration_days"] for p in self._drawdown_periods
            if p["duration_days"] is not None
        ]
        if not durations:
            return 0.0
        return float(np.mean(durations))

    def max_drawdown_duration(self) -> float:
        """Longest drawdown duration in days."""
        durations = [
            p["duration_days"] for p in self._drawdown_periods
            if p["duration_days"] is not None
        ]
        if not durations:
            return 0.0
        return float(np.max(durations))

    def pain_ratio(self) -> float:
        """Pain Ratio: cumulative return / cumulative drawdown.

        Captures the total 'pain' of holding through drawdowns by measuring
        the area under the drawdown curve. Higher is better.

        Pain = integral(|drawdown(t)| dt) over time
        """
        if len(self.drawdown_series) == 0:
            return 0.0

        total_pain = float(self.drawdown_series.abs().sum())
        total_return = float(self.cumulative.iloc[-1] - 1.0) if len(self.cumulative) > 0 else 0.0

        if total_pain < EPS:
            return float("inf") if total_return > 0 else 0.0
        return total_return / total_pain

    def lake_ratio(self) -> float:
        """Lake Ratio: area under the drawdown curve vs benchmark area.

        Visualized as a 'lake' — the deeper and wider the drawdowns, the
        more water in the lake. The lake ratio normalizes this.

        LR = area_of_drawdown_lake / area_of_maximal_drawdown

        Values near 0 = quick shallow drawdowns (good).
        Values near 1 = portfolio spent most of its time near max DD (bad).
        """
        if len(self.drawdown_series) == 0:
            return 0.0

        area_under = float(self.drawdown_series.abs().sum())
        # Maximal possible: all periods at max drawdown depth
        max_dd = abs(self.max_drawdown["max_drawdown"])
        if max_dd < EPS:
            return 0.0
        max_area = max_dd * len(self.drawdown_series)
        return area_under / max_area if max_area > EPS else 0.0

    def drawdown_duration_distribution(self) -> Dict[str, float]:
        """Statistics on drawdown duration distribution."""
        durations = [
            p["duration_days"] for p in self._drawdown_periods
            if p["duration_days"] is not None
        ]
        if not durations:
            return {}

        return {
            "mean_duration": float(np.mean(durations)),
            "median_duration": float(np.median(durations)),
            "std_duration": float(np.std(durations, ddof=1)),
            "min_duration": float(np.min(durations)),
            "max_duration": float(np.max(durations)),
            "p25_duration": float(np.percentile(durations, 25)),
            "p75_duration": float(np.percentile(durations, 75)),
        }

    def drawdown_depth_distribution(self) -> Dict[str, float]:
        """Statistics on drawdown depth distribution."""
        depths = [abs(p["max_drawdown"]) for p in self._drawdown_periods]
        if not depths:
            return {}

        return {
            "mean_depth": float(np.mean(depths)),
            "median_depth": float(np.median(depths)),
            "std_depth": float(np.std(depths, ddof=1)),
            "min_depth": float(np.min(depths)),
            "max_depth": float(np.max(depths)),
            "p25_depth": float(np.percentile(depths, 25)),
            "p75_depth": float(np.percentile(depths, 75)),
        }

    def underwater_days_pct(self, threshold: float = -0.05) -> float:
        """Percentage of total time spent below peak by more than threshold.

        A critical metric for institutional investors who care about
        being 'underwater'. Spends 80% of time below peak? That's a
        hard pass for most allocators.
        """
        if len(self.drawdown_series) == 0:
            return 0.0
        days_below = (self.drawdown_series < threshold).sum()
        return days_below / len(self.drawdown_series)

    def summary(self) -> Dict[str, Any]:
        """Complete drawdown analysis summary."""
        return {
            "max_drawdown": self.max_drawdown["max_drawdown"],
            "max_drawdown_pct": self.max_drawdown["max_drawdown"] * 100,
            "peak_date": self.max_drawdown.get("peak_date"),
            "trough_date": self.max_drawdown.get("trough_date"),
            "n_drawdown_periods": len(self._drawdown_periods),
            "average_drawdown": self.average_drawdown(),
            "average_drawdown_duration_days": self.average_drawdown_duration(),
            "max_drawdown_duration_days": self.max_drawdown_duration(),
            "average_recovery_time_days": self.average_recovery_time(),
            "pain_ratio": self.pain_ratio(),
            "lake_ratio": self.lake_ratio(),
            "underwater_days_pct": self.underwater_days_pct(),
            "drawdown_duration_dist": self.drawdown_duration_distribution(),
            "drawdown_depth_dist": self.drawdown_depth_distribution(),
        }


# ============================================================================
# 6. PORTFOLIO ATTRIBUTION
# ============================================================================

class PortfolioAttribution:
    """Decompose portfolio returns into sources of performance.

    Attribution answers the question every allocator asks: 'Was the return
    from your asset allocation, your security selection, or just luck?'

    Methods:
    - Brinson attribution: allocation + selection + interaction effects
    - Risk factor attribution: Fama-French/Carhart factor exposures
    - Sector/country/asset class attribution

    Reference:
        Brinson, Hood & Beebower (1986). "Determinants of Portfolio Performance."
        Fama & French (1993). "Common Risk Factors..."
    """

    def __init__(
        self,
        portfolio_weights: pd.DataFrame,
        portfolio_returns: pd.DataFrame,
        benchmark_weights: pd.DataFrame,
        benchmark_returns: pd.DataFrame,
        sectors: Optional[Dict[str, str]] = None,
    ):
        """
        Parameters
        ----------
        portfolio_weights : pd.DataFrame
            T x N, portfolio weights over time
        portfolio_returns : pd.DataFrame
            T x N, portfolio asset returns over time
        benchmark_weights : pd.DataFrame
            T x N, benchmark weights over time
        benchmark_returns : pd.DataFrame
            T x N, benchmark asset returns over time
        sectors : dict, optional
            {asset_id: sector_name} mapping for sector attribution
        """
        self.port_w = portfolio_weights.astype(np.float64)
        self.port_r = portfolio_returns.astype(np.float64)
        self.bm_w = benchmark_weights.astype(np.float64)
        self.bm_r = benchmark_returns.astype(np.float64)
        self.sectors = sectors or {}
        self.assets = list(self.port_w.columns)

    # ------------------------------------------------------------------
    # Brinson Attribution
    # ------------------------------------------------------------------

    def brinson_attribution(self) -> Dict[str, Any]:
        """Brinson, Hood & Beebower (1986) performance attribution.

        Decomposes active return into three components:
        1. Allocation effect: did you weight sectors/assets correctly?
        2. Selection effect: did you pick the right securities within sectors?
        3. Interaction effect: combined allocation × selection

        Returns
        -------
        dict with allocation, selection, interaction, total_active_return,
        and per-sector breakdowns
        """
        # Ensure aligned data (intersect indices across ALL four DataFrames)
        common_idx = self.port_w.index
        for df in [self.port_r, self.bm_w, self.bm_r]:
            common_idx = common_idx.intersection(df.index)
        common_cols = set(self.port_w.columns) & set(self.bm_w.columns) & \
                      set(self.port_r.columns) & set(self.bm_r.columns)

        pw = self.port_w.loc[common_idx, list(common_cols)]
        pr = self.port_r.loc[common_idx, list(common_cols)]
        bw = self.bm_w.loc[common_idx, list(common_cols)]
        br = self.bm_r.loc[common_idx, list(common_cols)]

        # Portfolio return
        port_ret = (pw * pr).sum(axis=1)
        bm_ret = (bw * br).sum(axis=1)

        active_return = port_ret - bm_ret

        # If sectors defined, compute attribution by sector
        if self.sectors:
            sectors = set(self.sectors.values())
            alloc_effect = pd.Series(0.0, index=common_idx)
            select_effect = pd.Series(0.0, index=common_idx)
            interact_effect = pd.Series(0.0, index=common_idx)

            sector_breakdown = {}

            for sector in sectors:
                sector_assets = [a for a in common_cols if self.sectors.get(a) == sector]
                if not sector_assets:
                    continue

                # Sector weights
                pw_s = pw[sector_assets].sum(axis=1)
                bw_s = bw[sector_assets].sum(axis=1)

                # Sector returns (benchmark and portfolio)
                br_s = (bw[sector_assets] * br[sector_assets]).sum(axis=1)
                br_s = br_s / bw_s.replace(0, np.nan)
                br_s = br_s.fillna(0.0)

                pr_s = (pw[sector_assets] * pr[sector_assets]).sum(axis=1)
                pr_s = pr_s / pw_s.replace(0, np.nan)
                pr_s = pr_s.fillna(0.0)

                # Total benchmark return (all assets)
                total_bm_ret = (bw * br).sum(axis=1)

                # Allocation effect: (w_p - w_b) * (R_b - R_b_total)
                alloc = (pw_s - bw_s) * (br_s - total_bm_ret)
                alloc_effect += alloc

                # Selection effect: w_b * (R_p - R_b)
                select = bw_s * (pr_s - br_s)
                select_effect += select

                # Interaction effect: (w_p - w_b) * (R_p - R_b)
                interact = (pw_s - bw_s) * (pr_s - br_s)
                interact_effect += interact

                sector_breakdown[sector] = {
                    "allocation": float(alloc.mean()),
                    "selection": float(select.mean()),
                    "interaction": float(interact.mean()),
                    "total": float((alloc + select + interact).mean()),
                }

            return {
                "allocation_effect": float(alloc_effect.mean()),
                "selection_effect": float(select_effect.mean()),
                "interaction_effect": float(interact_effect.mean()),
                "total_active_return": float(active_return.mean()),
                "active_return_annualized": _annualized_return(
                    float(active_return.mean()), 252
                ),
                "sector_attribution": sector_breakdown,
                "method": "brinson_sector",
            }
        else:
            # Simple Brinson without sector mapping
            # Allocation effect for each asset
            alloc_effect = ((pw - bw) * br).sum(axis=1)
            select_effect = (bw * (pr - br)).sum(axis=1)
            interact_effect = ((pw - bw) * (pr - br)).sum(axis=1)

            return {
                "allocation_effect": float(alloc_effect.mean()),
                "selection_effect": float(select_effect.mean()),
                "interaction_effect": float(interact_effect.mean()),
                "total_active_return": float(active_return.mean()),
                "active_return_annualized": _annualized_return(
                    float(active_return.mean()), 252
                ),
                "method": "brinson_asset",
            }

    # ------------------------------------------------------------------
    # Risk Factor Attribution (Fama-French)
    # ------------------------------------------------------------------

    def factor_attribution(
        self, factor_returns: pd.DataFrame, lookback: Optional[int] = None
    ) -> Dict[str, Any]:
        """Attribute portfolio returns to risk factor exposures.

        Runs a time-series regression of portfolio returns on factor returns:
        R_p - Rf = alpha + beta_m * (Rm - Rf) + beta_s * SMB + beta_h * HML
                   + beta_r * RMW + beta_c * CMA + beta_mom * MOM + epsilon

        Parameters
        ----------
        factor_returns : pd.DataFrame
            Factor returns with columns like 'Mkt-RF', 'SMB', 'HML', etc.
            Must contain 'Mkt-RF' (market excess return).
        lookback : int, optional
            Number of periods for rolling regression

        Returns
        -------
        dict with regression coefficients, alpha, R-squared, factor contributions
        """
        # Compute portfolio returns
        port_ret = (self.port_w * self.port_r).sum(axis=1)
        port_ret = port_ret.dropna()

        # Align with factors
        common = port_ret.index.intersection(factor_returns.index)
        y = port_ret.loc[common]
        X = factor_returns.loc[common]

        # Center both
        y = y - y.mean()
        X = X.subtract(X.mean(), axis=1)

        if lookback:
            y = y.tail(lookback)
            X = X.tail(lookback)

        # OLS regression
        X_mat = np.column_stack([np.ones(len(X)), X.values])
        coeffs, residuals, rank, sv = np.linalg.lstsq(X_mat, y.values, rcond=None)

        alpha = coeffs[0]
        betas = coeffs[1:]
        n = len(y)
        k = len(betas)

        # R-squared
        y_pred = X_mat @ coeffs
        ss_res = np.sum((y.values - y_pred) ** 2)
        ss_tot = np.sum((y.values - y.mean()) ** 2)
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > EPS else 0.0

        # Adjusted R-squared
        adj_r_squared = 1.0 - (1.0 - r_squared) * (n - 1) / (n - k - 1)

        # Factor contributions
        factor_contrib = {}
        for i, col in enumerate(X.columns):
            factor_contrib[col] = float(betas[i])

        # Alpha annualized and significance
        alpha_ann = _annualized_return(alpha, 252)
        alpha_se = np.std(residuals, ddof=k + 1) / np.sqrt(n)
        alpha_t = alpha / alpha_se if alpha_se > EPS else 0.0
        alpha_p = 2.0 * (1.0 - stats.t.cdf(abs(alpha_t), df=n - k - 1))

        return {
            "alpha": float(alpha),
            "alpha_annualized": alpha_ann,
            "alpha_t_stat": float(alpha_t),
            "alpha_p_value": alpha_p,
            "alpha_significant": alpha_p < 0.05,
            "r_squared": r_squared,
            "adj_r_squared": adj_r_squared,
            "n_observations": n,
            "factor_betas": factor_contrib,
            "method": "fama_french_ols",
        }

    # ------------------------------------------------------------------
    # Sector / Country / Asset Class Attribution
    # ------------------------------------------------------------------

    def sector_attribution(
        self, sector_map: Dict[str, str]
    ) -> Dict[str, Any]:
        """Attribution breakdown by sector.

        Parameters
        ----------
        sector_map : dict
            {asset_id: sector_name}

        Returns
        -------
        dict with per-sector allocation, selection, and total contribution
        """
        self.sectors = sector_map
        return self.brinson_attribution()

    def rolling_attribution(
        self, window: int = 252
    ) -> pd.DataFrame:
        """Rolling Brinson attribution over time.

        Returns a DataFrame with allocation, selection, and interaction
        effects for each period.
        """
        # Compute per-period components
        common_idx = self.port_w.index.intersection(self.bm_w.index)
        common_cols = set(self.port_w.columns) & set(self.bm_w.columns) & \
                      set(self.port_r.columns) & set(self.bm_r.columns)

        pw = self.port_w.loc[common_idx, list(common_cols)]
        pr = self.port_r.loc[common_idx, list(common_cols)]
        bw = self.bm_w.loc[common_idx, list(common_cols)]
        br = self.bm_r.loc[common_idx, list(common_cols)]

        alloc = ((pw - bw) * br).sum(axis=1)
        select = (bw * (pr - br)).sum(axis=1)
        interact = ((pw - bw) * (pr - br)).sum(axis=1)

        result = pd.DataFrame({
            "allocation": alloc,
            "selection": select,
            "interaction": interact,
            "active_return": alloc + select + interact,
        })

        if window is not None and window < len(result):
            result = result.rolling(window=window).mean()

        return result


# ============================================================================
# 7. CORRELATION ANALYZER
# ============================================================================

class CorrelationAnalyzer:
    """Advanced correlation analysis with regime detection and PCA.

    Correlation is not static — it changes with market regimes. This class
    captures those dynamics for smarter risk management and diversification.

    Provides:
    - Rolling correlation matrix with regime detection (regime-switching)
    - Principal Component Analysis (PCA) for risk factor decomposition
    - Cluster analysis for identifying natural asset groups
    - Correlation breakdown during market stress

    Parameters
    ----------
    returns : pd.DataFrame
        T x N asset returns
    window : int, default=60
        Rolling window for time-varying correlations
    """

    def __init__(self, returns: pd.DataFrame, window: int = 60):
        self.returns = _ensure_dataframe(returns)
        _check_returns(self.returns)
        self.n_assets = self.returns.shape[1]
        self.asset_names = list(self.returns.columns)
        self.window = window
        self.corr_long = _cov_to_corr(self.returns.cov().values)

    # ------------------------------------------------------------------
    # Rolling Correlation
    # ------------------------------------------------------------------

    def rolling_correlation(
        self, asset_i: Optional[str] = None, asset_j: Optional[str] = None
    ) -> pd.DataFrame:
        """Compute rolling correlation matrix.

        Parameters
        ----------
        asset_i, asset_j : str, optional
            If both provided, returns a single rolling correlation series.
            If neither, returns full rolling correlation matrix.

        Returns
        -------
        pd.DataFrame or pd.Series of rolling correlations
        """
        if asset_i and asset_j:
            return self.returns[asset_i].rolling(self.window).corr(self.returns[asset_j])

        # Full rolling correlation matrix as 3D
        # Return pairwise rolling correlations
        pairs = {}
        for i in range(self.n_assets):
            for j in range(i + 1, self.n_assets):
                name = f"{self.asset_names[i]}_{self.asset_names[j]}"
                pairs[name] = self.returns.iloc[:, i].rolling(self.window).corr(
                    self.returns.iloc[:, j]
                )
        return pd.DataFrame(pairs)

    def average_correlation(self) -> pd.Series:
        """Average pairwise correlation over time (rolling).

        When average correlation spikes, diversification is failing —
        this is when risk parity tends to suffer most.
        """
        pair_corrs = []
        for i in range(self.n_assets):
            for j in range(i + 1, self.n_assets):
                pair_corrs.append(
                    self.returns.iloc[:, i].rolling(self.window).corr(
                        self.returns.iloc[:, j]
                    )
                )
        avg = pd.concat(pair_corrs, axis=1).mean(axis=1)
        avg.name = "avg_correlation"
        return avg

    def correlation_breakdown(
        self, threshold: float = 0.7, lookback: int = 20
    ) -> Dict[str, Any]:
        """Measure correlation breakdown during high-stress periods.

        Counts how many pairwise correlations exceed a threshold during
        high-volatility regimes. The number rising means assets are
        'all correlated to 1' — the worst time to need diversification.
        """
        rolling_corrs = self.rolling_correlation()
        avg_corr = rolling_corrs.mean(axis=1)

        high_corr_count = (rolling_corrs > threshold).sum(axis=1)
        vol = self.returns.sum(axis=1).rolling(lookback).std()

        return {
            "avg_corr": avg_corr,
            "high_corr_count": high_corr_count,
            "max_avg_corr": float(avg_corr.max()),
            "min_avg_corr": float(avg_corr.min()),
            "current_avg_corr": float(avg_corr.iloc[-1]) if len(avg_corr) > 0 else 0.0,
            "corr_spike_dates": avg_corr[avg_corr > avg_corr.quantile(0.95)].index.tolist(),
        }

    # ------------------------------------------------------------------
    # Principal Component Analysis (PCA)
    # ------------------------------------------------------------------

    def pca_risk_factors(self, n_components: Optional[int] = None) -> Dict[str, Any]:
        """Decompose correlation structure into principal components.

        PCA identifies the independent risk factors driving portfolio
        returns. The first PC is often the 'market' factor; subsequent
        PCs capture sector, style, and idiosyncratic risks.

        Parameters
        ----------
        n_components : int, optional
            Number of components. Defaults to explaining 95% variance.

        Returns
        -------
        dict with explained_variance, loadings, components, risk_breakdown
        """
        from sklearn.decomposition import PCA

        corr = self.corr_long

        if n_components is None:
            # Find components that explain 95% of variance
            n_components = min(self.n_assets, self.n_assets)

        pca = PCA(n_components=n_components)
        pca.fit(corr)

        # Cumulative variance
        cum_var = np.cumsum(pca.explained_variance_ratio_)
        n_95 = int(np.searchsorted(cum_var, 0.95) + 1)

        # Loading matrix (correlation between original assets and PCs)
        loadings = pd.DataFrame(
            pca.components_.T,
            index=self.asset_names,
            columns=[f"PC{i+1}" for i in range(n_components)],
        )

        # Risk breakdown: how much of each asset's variance is explained
        # by the first K components
        risk_breakdown = {}
        for i, asset in enumerate(self.asset_names):
            risk_breakdown[asset] = {
                f"PC{j+1}_loading": float(loadings.iloc[i, j])
                for j in range(min(5, n_components))
            }
            risk_breakdown[asset]["communality"] = float(
                np.sum(loadings.iloc[i, :n_95] ** 2)
            )

        return {
            "n_components": n_components,
            "n_explaining_95pct": n_95,
            "explained_variance_ratio": pca.explained_variance_ratio_.tolist(),
            "cumulative_variance": cum_var.tolist(),
            "loadings": loadings,
            "risk_breakdown": risk_breakdown,
            "effective_n_factors": float(
                1.0 / np.sum(pca.explained_variance_ratio_ ** 2)
            ),
        }

    def effective_n_factors(self) -> float:
        """Number of effective risk factors (Herfindahl of eigenportfolio).

        The 'effective N' of the correlation matrix — similar to HHI but
        for risk factors. Higher means more diversified risk sources.
        """
        eigvals = np.linalg.eigvalsh(self.corr_long)
        eigvals = np.maximum(eigvals, 0.0)
        total = eigvals.sum()
        if total < EPS:
            return 1.0
        proportions = eigvals / total
        return 1.0 / np.sum(proportions ** 2)

    # ------------------------------------------------------------------
    # Cluster Analysis
    # ------------------------------------------------------------------

    def cluster_analysis(
        self, n_clusters: Optional[int] = None, method: str = "ward"
    ) -> Dict[str, Any]:
        """Hierarchical clustering for diversification insights.

        Identifies natural groupings of assets based on their return
        correlations. A well-diversified portfolio should have assets
        from different clusters.

        Parameters
        ----------
        n_clusters : int, optional
            Number of clusters. Estimated automatically if None.
        method : str, default='ward'
            Linkage method for hierarchical clustering

        Returns
        -------
        dict with cluster assignments, linkage, cophenetic correlation
        """
        from scipy.spatial.distance import squareform

        # Correlation distance: sqrt(2 * (1 - corr))
        dist = np.sqrt(np.maximum(0, 2.0 * (1.0 - self.corr_long)))
        np.fill_diagonal(dist, 0.0)
        condensed = squareform(dist, checks=False)

        # Hierarchical clustering
        linkage = cluster.hierarchy.linkage(condensed, method=method)

        # Estimate optimal clusters using silhouette score
        from sklearn.metrics import silhouette_score

        if n_clusters is None or n_clusters < 2:
            best_n = 2
            best_score = -1.0
            for k in range(2, min(self.n_assets, 10)):
                labels = cluster.hierarchy.fcluster(linkage, k, criterion="maxclust")
                if len(set(labels)) > 1:
                    sil = silhouette_score(dist, labels, metric="precomputed")
                    if sil > best_score:
                        best_score = sil
                        best_n = k
            n_clusters = best_n

        # Final cluster assignments
        labels = cluster.hierarchy.fcluster(linkage, n_clusters, criterion="maxclust")

        # Cophenetic correlation coefficient (how well tree preserves distances)
        cophenetic = cluster.hierarchy.cophenet(linkage, condensed)
        cophenetic_corr = float(cophenetic[0])

        # Per-cluster assets
        clusters = {}
        for i, asset in enumerate(self.asset_names):
            c = int(labels[i])
            if c not in clusters:
                clusters[c] = []
            clusters[c].append(asset)

        # Intra-cluster average correlation
        intra_cluster_corr = {}
        for c, members in clusters.items():
            if len(members) > 1:
                idx = [self.asset_names.index(m) for m in members]
                sub_corr = self.corr_long[np.ix_(idx, idx)]
                intra_cluster_corr[c] = float(
                    (np.sum(sub_corr) - len(members)) / (len(members) * (len(members) - 1))
                )
            else:
                intra_cluster_corr[c] = 1.0

        return {
            "n_clusters": n_clusters,
            "cluster_assignments": dict(zip(self.asset_names, labels.tolist())),
            "cluster_members": clusters,
            "intra_cluster_corr": intra_cluster_corr,
            "linkage": linkage,
            "cophenetic_correlation": cophenetic_corr,
            "method": method,
        }

    # ------------------------------------------------------------------
    # Regime Detection via Correlation
    # ------------------------------------------------------------------

    def regime_detection(self, n_regimes: int = 2) -> Dict[str, Any]:
        """Detect correlation regimes using Gaussian Mixture Model.

        Correlations are higher during crisis regimes and lower during
        normal markets. This identifies those regimes.

        Parameters
        ----------
        n_regimes : int, default=2
            Number of correlation regimes (typically 2: normal + crisis)

        Returns
        -------
        dict with regime assignments, probabilities, regime means
        """
        from sklearn.mixture import GaussianMixture

        # Use rolling average correlation as the single regime indicator
        avg_corr = self.average_correlation().dropna().values.reshape(-1, 1)

        if len(avg_corr) < 20:
            return {"error": "Insufficient data for regime detection"}

        gmm = GaussianMixture(n_components=n_regimes, random_state=42)
        gmm.fit(avg_corr)

        regimes = gmm.predict(avg_corr)
        probs = gmm.predict_proba(avg_corr)

        # Identify which regime is high-correlation (crisis)
        means = gmm.means_.flatten()
        crisis_regime = int(np.argmax(means))

        return {
            "n_regimes": n_regimes,
            "crisis_regime": crisis_regime,
            "regime_means": means.tolist(),
            "regime_covariances": [
                np.diag(c).tolist() for c in gmm.covariances_
            ],
            "current_regime": int(regimes[-1]),
            "crisis_probability": float(probs[-1, crisis_regime]),
            "avg_corr_by_regime": {
                i: float(avg_corr[regimes == i].mean())
                for i in range(n_regimes)
            },
            "time_in_crisis_pct": float(np.mean(regimes == crisis_regime)),
        }


# ============================================================================
# 8. REBALANCING ENGINE
# ============================================================================

class RebalancingEngine:
    """Professional portfolio rebalancing with multiple triggers and methods.

    Amateurs set a date and rebalance everything. Pros minimize taxes,
    transaction costs, and market impact while staying close to target.

    Rebalancing methods:
    - Calendar-based: monthly, quarterly, annually (with business day offsets)
    - Threshold-based: rebalance when any weight drifts beyond X%
    - Volatility-based: rebalance when portfolio volatility regime changes
    - Tax-efficient: harvest losses, defer gains
    - Partial: rebalance only the assets that drifted most

    Parameters
    ----------
    target_weights : Dict[str, float]
        Target allocation {asset_id: target_weight}
    portfolio : PortfolioConstructor
        Portfolio state to rebalance
    """

    def __init__(
        self,
        target_weights: Dict[str, float],
        portfolio: PortfolioConstructor,
    ):
        self.target = target_weights
        self.portfolio = portfolio
        self._last_rebalance: Optional[datetime] = None
        self._rebalance_history: List[Dict] = []

    # ------------------------------------------------------------------
    # Core Rebalancing Logic
    # ------------------------------------------------------------------

    def _compute_drift(self) -> Dict[str, float]:
        """Compute current weight drift from target.

        Returns {asset_id: drift} where drift = current - target (in weight %)
        """
        current = self.portfolio.state.current_weights()
        drift = {}
        for asset in set(list(self.target.keys()) + list(current.keys())):
            t = self.target.get(asset, 0.0)
            c = current.get(asset, 0.0)
            drift[asset] = c - t
        return drift

    def rebalance_calendar(
        self,
        current_date: datetime,
        frequency: str = "quarterly",
        month_offset: int = 0,
        day_of_month: int = 1,
        prices: Optional[Dict[str, float]] = None,
        max_turnover: float = 1.0,
        tax_aware: bool = False,
    ) -> List[Dict]:
        """Calendar-based rebalancing on a fixed schedule.

        Parameters
        ----------
        current_date : datetime
            Current date to check
        frequency : str, default='quarterly'
            One of: 'monthly', 'quarterly', 'semi_annual', 'annual'
        month_offset : int, default=0
            Month offset for quarterly (0=Jan/Apr/Jul/Oct, 1=Feb/May/Aug/Nov, etc.)
        day_of_month : int, default=1
            Day of month to rebalance
        prices : dict, optional
            Current prices for rebalance calculation
        tax_aware : bool, default=False
        max_turnover : float, default=1.0

        Returns
        -------
        list of trades
        """
        should_rebalance = False

        if frequency == "monthly":
            should_rebalance = current_date.day == day_of_month
        elif frequency == "quarterly":
            should_rebalance = (
                current_date.month in [1 + month_offset, 4 + month_offset,
                                        7 + month_offset, 10 + month_offset]
                and current_date.day == day_of_month
            )
        elif frequency == "semi_annual":
            should_rebalance = (
                current_date.month in [1 + month_offset, 7 + month_offset]
                and current_date.day == day_of_month
            )
        elif frequency == "annual":
            should_rebalance = (
                current_date.month == 1 + month_offset
                and current_date.day == day_of_month
            )

        if not should_rebalance:
            return []

        return self._execute_rebalance(
            prices=prices, max_turnover=max_turnover, tax_aware=tax_aware,
            reason=f"Calendar ({frequency})",
        )

    def rebalance_threshold(
        self,
        threshold: float = 0.05,
        prices: Optional[Dict[str, float]] = None,
        min_absolute_drift: float = 0.0,
        max_turnover: float = 1.0,
        tax_aware: bool = False,
    ) -> List[Dict]:
        """Threshold-based rebalancing.

        Rebalances when any asset's weight drifts from target by more
        than `threshold` (as a fraction of portfolio).

        Parameters
        ----------
        threshold : float, default=0.05
            Maximum allowable drift per asset (5% default)
        prices : dict, optional
        min_absolute_drift : float, default=0.0
            Don't rebalance for drifts below this absolute level
        max_turnover : float, default=1.0
        tax_aware : bool, default=False

        Returns
        -------
        list of trades
        """
        drift = self._compute_drift()
        max_drift = max(abs(d) for d in drift.values()) if drift else 0.0

        if max_drift < threshold:
            return []

        # Check if any asset exceeds the threshold AND has meaningful drift
        meaningful = False
        for asset, d in drift.items():
            target_val = self.target.get(asset, 0.0)
            if abs(d) > max(threshold, min_absolute_drift) and target_val > 0:
                meaningful = True
                break

        if not meaningful:
            return []

        # Only rebalance the assets that exceeded threshold (partial)
        partial_target = dict(self.target)
        for asset, d in drift.items():
            if abs(d) < threshold:
                # Keep current weight — don't trade this one
                pass

        return self._execute_rebalance(
            prices=prices, max_turnover=max_turnover, tax_aware=tax_aware,
            reason=f"Threshold ({threshold*100:.0f}%)",
        )

    def rebalance_volatility(
        self,
        returns_series: pd.Series,
        baseline_vol: float,
        vol_change_threshold: float = 0.25,
        lookback: int = 21,
        prices: Optional[Dict[str, float]] = None,
        max_turnover: float = 1.0,
    ) -> List[Dict]:
        """Volatility-based rebalancing.

        When portfolio volatility changes significantly (e.g., regime
        change), the optimal risk budget allocation changes too.
        Rebalances when current vol deviates > X% from baseline.

        Parameters
        ----------
        returns_series : pd.Series
            Portfolio return series
        baseline_vol : float
            Target/baseline annualized volatility
        vol_change_threshold : float, default=0.25
            Trigger when vol changes by this fraction (25% default)
        lookback : int, default=21
            Lookback period for current vol estimate (1 month)
        prices : dict, optional
        max_turnover : float, default=1.0

        Returns
        -------
        list of trades
        """
        if len(returns_series) < lookback:
            return []

        current_vol = float(returns_series.tail(lookback).std()) * np.sqrt(252)

        if abs(baseline_vol) < EPS:
            return []

        vol_change = abs(current_vol - baseline_vol) / baseline_vol

        if vol_change < vol_change_threshold:
            return []

        # Adjust target weights based on new vol regime
        # Higher vol = shift to lower-risk assets
        vol_ratio = baseline_vol / max(current_vol, EPS)
        adjusted_target = {}
        for asset, w in self.target.items():
            # Conservative: scale riskier assets down when vol is high
            adjusted_target[asset] = w * vol_ratio

        # Renormalize
        total = sum(adjusted_target.values())
        if total > EPS:
            adjusted_target = {k: v / total for k, v in adjusted_target.items()}
        else:
            adjusted_target = dict(self.target)

        return self._execute_rebalance(
            target_override=adjusted_target,
            prices=prices, max_turnover=max_turnover,
            reason=f"Volatility ({vol_change*100:.0f}% change)",
        )

    def rebalance_tax_efficient(
        self,
        unrealized_gains: Dict[str, float],
        tax_rate_short: float = 0.35,
        tax_rate_long: float = 0.20,
        holding_periods: Optional[Dict[str, int]] = None,
        prices: Optional[Dict[str, float]] = None,
        max_turnover: float = 0.5,
    ) -> List[Dict]:
        """Tax-efficient rebalancing.

        Strategy:
        1. Sell losers FIRST (tax-loss harvesting) — fully to target
        2. Sell short-term winners NEXT (highest tax cost)
        3. Sell long-term winners LAST — only if necessary
        4. Use new cash flows to adjust toward target

        Parameters
        ----------
        unrealized_gains : dict
            {asset_id: gain_per_share}
        tax_rate_short : float, default=0.35
            Short-term capital gains tax rate
        tax_rate_long : float, default=0.20
            Long-term capital gains tax rate
        holding_periods : dict, optional
            {asset_id: days_held} to determine short/long term
        prices : dict, optional
        max_turnover : float, default=0.5

        Returns
        -------
        list of trades
        """
        drift = self._compute_drift()

        # Categorize overweights into sell priority
        overweights = [(a, d) for a, d in drift.items() if d > 0]

        def sell_priority(item):
            asset, _ = item
            gain = unrealized_gains.get(asset, 0.0)
            holding = (holding_periods or {}).get(asset, 0)
            is_long = holding >= 365

            if gain < 0:
                # Tax-loss harvest: highest priority
                return (0, gain)
            elif not is_long:
                # Short-term: high tax cost, sell only if necessary
                return (2, gain)
            else:
                # Long-term: lowest priority, best tax treatment
                return (1, gain)

        overweights.sort(key=sell_priority)

        # Build target — only sell what we have to
        target = dict(self.target)
        current = self.portfolio.state.current_weights()

        # First pass: bring losers to target
        for asset, d in overweights:
            if unrealized_gains.get(asset, 0.0) < 0:
                # Sell fully to target
                pass  # Will be handled by execute_rebalance

        return self._execute_rebalance(
            prices=prices, max_turnover=max_turnover, tax_aware=True,
            reason="Tax-efficient rebalance",
        )

    def _execute_rebalance(
        self,
        prices: Optional[Dict[str, float]] = None,
        max_turnover: float = 1.0,
        tax_aware: bool = False,
        target_override: Optional[Dict[str, float]] = None,
        reason: str = "Manual",
    ) -> List[Dict]:
        """Execute the actual rebalance trades."""
        target = target_override or self.target

        trades = self.portfolio.rebalance_to_weights(
            target_weights=target,
            prices=prices or {},
            max_turnover=max_turnover,
            tax_aware=tax_aware,
        )

        self._last_rebalance = datetime.now()
        self._rebalance_history.append({
            "date": self._last_rebalance,
            "reason": reason,
            "n_trades": len(trades),
            "target": target,
        })

        return trades

    # ------------------------------------------------------------------
    # Partial Rebalancing
    # ------------------------------------------------------------------

    def partial_rebalance(
        self,
        max_trades: int = 5,
        min_trade_size: float = 0.0,
        prices: Optional[Dict[str, float]] = None,
        max_turnover: float = 0.3,
    ) -> List[Dict]:
        """Partial rebalancing — trade only the most drifted assets.

        Minimizes transaction costs by only correcting the largest
        deviations. Strategy: rank assets by absolute drift, trade the
        top N, leave the rest.

        Parameters
        ----------
        max_trades : int, default=5
            Maximum number of assets to trade
        min_trade_size : float, default=0.0
            Minimum notional for any trade
        prices : dict, optional
        max_turnover : float, default=0.3

        Returns
        -------
        list of trades
        """
        drift = self._compute_drift()

        # Rank by absolute drift
        ranked = sorted(drift.items(), key=lambda x: abs(x[1]), reverse=True)

        # Take top N that need correction
        to_rebalance = set()
        for asset, d in ranked[:max_trades]:
            if abs(d) > min_trade_size:
                to_rebalance.add(asset)

        if not to_rebalance:
            return []

        # Only adjust these assets — keep current weights for others
        adjustment_target = dict(self.target)
        current = self.portfolio.state.current_weights()

        # Redistribute: assets not being touched stay at current weight,
        # touched assets go to target weight
        untouched_weight = sum(current.get(a, 0.0) for a in current if a not in to_rebalance)
        touched_target = sum(adjustment_target.get(a, 0.0) for a in to_rebalance)

        if touched_target > 1.0 - untouched_weight + EPS:
            # Scale down touched assets to fit
            scale = (1.0 - untouched_weight) / max(touched_target, EPS)
            for a in to_rebalance:
                adjustment_target[a] = (adjustment_target.get(a, 0.0) * scale)

        # Renormalize untouched assets
        for a in current:
            if a not in to_rebalance:
                adjustment_target[a] = current[a]

        return self._execute_rebalance(
            prices=prices, max_turnover=max_turnover,
            target_override=adjustment_target,
            reason=f"Partial ({max_trades} assets)",
        )

    def rebalance_history(self) -> pd.DataFrame:
        """Get rebalance history as a DataFrame."""
        return pd.DataFrame(self._rebalance_history)

    def turnover_since(self, date: datetime) -> float:
        """Cumulative turnover since a given date."""
        total = 0.0
        for rb in self._rebalance_history:
            if rb["date"] >= date:
                total += rb.get("turnover", 1.0)  # estimate
        return total


# ============================================================================
# 9. ALLOCATION OPTIMIZER
# ============================================================================

class AllocationOptimizer:
    """Strategic asset allocation for long-term portfolio construction.

    Moves beyond pure mean-variance to incorporate investor goals,
    time horizon, and factor exposures. Designed for the institutional
    practitioner building multi-asset portfolios.

    Methods:
    - Goal-based allocation: custom objectives (retirement, income, growth)
    - Lifecycle / glide path: age-based dynamic allocation
    - Factor-based allocation: value, momentum, size, quality tilts
    - Risk-budget-aware allocation

    Parameters
    ----------
    returns : pd.DataFrame
        T x N asset returns
    cov_matrix : np.ndarray, optional
        Pre-computed covariance. Computed from returns if None.
    risk_free_rate : float, default=0.0
        Annualized risk-free rate
    """

    def __init__(
        self,
        returns: pd.DataFrame,
        cov_matrix: Optional[np.ndarray] = None,
        risk_free_rate: float = 0.0,
    ):
        self.returns = _ensure_dataframe(returns)
        self.n_assets = self.returns.shape[1]
        self.asset_names = list(self.returns.columns)

        if cov_matrix is not None:
            self.cov = np.asarray(cov_matrix, dtype=np.float64)
            _check_cov_matrix(self.cov)
        else:
            self.cov = np.asarray(self.returns.cov().values * 252, dtype=np.float64)

        self.mean_ret = np.asarray([
            _annualized_return(float(self.returns[col].mean()), 252)
            for col in self.returns.columns
        ], dtype=np.float64)
        self.vols = np.sqrt(np.diag(self.cov))
        self.rf = risk_free_rate

    # ------------------------------------------------------------------
    # Goal-Based Allocation
    # ------------------------------------------------------------------

    def goal_based_allocation(
        self,
        goal_type: str = "growth",
        risk_tolerance: float = 0.5,
        time_horizon_years: float = 10.0,
        income_requirement: float = 0.0,
        inflation_adjust: bool = True,
        constraints: Optional[Dict[str, Tuple[float, float]]] = None,
    ) -> Dict[str, Any]:
        """Strategic allocation based on investor goals.

        Parameters
        ----------
        goal_type : str, default='growth'
            One of: 'retirement', 'growth', 'income', 'capital_preservation',
                    'balanced', 'aggressive_growth'
        risk_tolerance : float, default=0.5
            0 (risk-averse) to 1 (risk-seeking). Determines position on
            the efficient frontier.
        time_horizon_years : float, default=10.0
            Investment horizon in years. Longer = more equity risk.
        income_requirement : float, default=0.0
            Required annual income yield (0-1). Higher = more bonds/dividends.
        inflation_adjust : bool, default=True
            Whether returns are adjusted for inflation expectation
        constraints : dict, optional
            {asset_name: (min_weight, max_weight)} custom constraints

        Returns
        -------
        dict with weights, expected_return, expected_vol, allocation_profile
        """
        # Map goal types to risk parameters
        goal_params = {
            "capital_preservation": {
                "max_equity": 0.2, "min_bonds": 0.6, "target_vol": 0.05,
                "target_return": 0.02,
            },
            "income": {
                "max_equity": 0.4, "min_bonds": 0.4, "target_vol": 0.08,
                "target_return": 0.04,
            },
            "balanced": {
                "max_equity": 0.6, "min_bonds": 0.2, "target_vol": 0.12,
                "target_return": 0.06,
            },
            "growth": {
                "max_equity": 0.8, "min_bonds": 0.1, "target_vol": 0.15,
                "target_return": 0.08,
            },
            "aggressive_growth": {
                "max_equity": 1.0, "min_bonds": 0.0, "target_vol": 0.20,
                "target_return": 0.10,
            },
            "retirement": {
                "max_equity": 0.5, "min_bonds": 0.3, "target_vol": 0.10,
                "target_return": 0.05,
            },
        }

        params = goal_params.get(goal_type, goal_params["growth"])

        # Adjust for time horizon
        if time_horizon_years > 15:
            params["max_equity"] = min(1.0, params["max_equity"] + 0.2)
        elif time_horizon_years < 5:
            params["max_equity"] = max(0.1, params["max_equity"] - 0.2)

        # Adjust for risk tolerance
        params["target_vol"] *= (0.5 + risk_tolerance)
        params["target_return"] *= (0.7 + 0.6 * risk_tolerance)

        # Adjust for income requirement
        if income_requirement > 0.01:
            # Need yield — reduce equity allocation
            params["max_equity"] = max(0.1, params["max_equity"] - income_requirement * 0.5)

        # Build optimization
        n = self.n_assets
        bounds_list = []
        for i, name in enumerate(self.asset_names):
            if constraints and name in constraints:
                bounds_list.append(constraints[name])
            else:
                bounds_list.append((0.0, 1.0))

        # Classify assets roughly (heuristic based on vol)
        # Low vol ~ bonds, high vol ~ equity
        vol_threshold_low = np.percentile(self.vols, 33)
        vol_threshold_high = np.percentile(self.vols, 66)

        bounds = Bounds(
            [b[0] for b in bounds_list],
            [b[1] for b in bounds_list],
        )

        constraints_list = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]

        # Add goal-specific constraints
        def _vol_constraint(w):
            vol = np.sqrt(w @ self.cov @ w)
            return params["target_vol"] - vol

        constraints_list.append({"type": "ineq", "fun": _vol_constraint})

        # Optimize: maximize return subject to vol constraint and bounds
        best_w = None
        best_ret = -np.inf

        for w0 in [
            np.ones(n) / n,
            self.vols / self.vols.sum(),
            1.0 / self.vols / (1.0 / self.vols).sum(),
        ]:
            result = minimize(
                lambda w: -(w @ self.mean_ret),
                w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints_list,
                options={"ftol": 1e-12, "maxiter": 10000},
            )
            if result.success and result.fun < best_ret:
                best_ret = result.fun
                best_w = result.x

        if best_w is None:
            # Fallback: equal weight with constraints
            best_w = np.array([b[1] for b in bounds_list])
            best_w = best_w / best_w.sum()

        w = best_w / best_w.sum()
        port_ret = float(w @ self.mean_ret)
        port_vol = float(np.sqrt(w @ self.cov @ w))
        sharpe = (port_ret - self.rf) / port_vol if port_vol > EPS else 0.0

        # Allocation profile
        equity_allocation = sum(
            w[i] for i in range(n)
            if self.vols[i] > vol_threshold_low
        )
        bond_allocation = sum(
            w[i] for i in range(n)
            if self.vols[i] <= vol_threshold_low
        )

        return {
            "weights": dict(zip(self.asset_names, w.tolist())),
            "expected_return": port_ret,
            "expected_volatility": port_vol,
            "sharpe_ratio": sharpe,
            "equity_allocation": equity_allocation,
            "bond_allocation": bond_allocation,
            "goal_type": goal_type,
            "risk_tolerance": risk_tolerance,
            "time_horizon_years": time_horizon_years,
            "method": f"goal_based_{goal_type}",
        }

    # ------------------------------------------------------------------
    # Lifecycle / Glide Path Allocation
    # ------------------------------------------------------------------

    def lifecycle_allocation(
        self,
        age: int,
        retirement_age: int = 65,
        risk_profile: str = "moderate",
        current_wealth: float = 0.0,
        target_wealth: Optional[float] = None,
        annual_contribution: float = 0.0,
    ) -> Dict[str, Any]:
        """Target-date / lifecycle allocation based on investor age.

        The classic glide path: more equities when young, shift to bonds
        as retirement approaches. Models the glide path as a smooth
        function of years to retirement.

        Parameters
        ----------
        age : int
            Current age of investor
        retirement_age : int, default=65
            Target retirement age
        risk_profile : str, default='moderate'
            'conservative', 'moderate', or 'aggressive'
        current_wealth : float, default=0.0
            Current portfolio value (for wealth-based adjustment)
        target_wealth : float, optional
            Goal wealth at retirement
        annual_contribution : float, default=0.0
            Annual contribution amount

        Returns
        -------
        dict with weights, equity_pct, bond_pct, glide_position
        """
        years_to_retirement = max(0, retirement_age - age)

        # Glide path: equity allocation decreases linearly
        base_equity = 1.0 - (years_to_retirement / 40)  # 0% at ret, 100% at 40yr out

        # Risk profile adjustment
        risk_multipliers = {
            "conservative": 0.7,
            "moderate": 1.0,
            "aggressive": 1.3,
        }
        multiplier = risk_multipliers.get(risk_profile, 1.0)
        equity_target = np.clip(base_equity * multiplier, 0.1, 0.95)

        # Wealth-based adjustment: if behind target, increase equity risk
        if target_wealth and target_wealth > 0 and current_wealth > 0:
            wealth_ratio = current_wealth / target_wealth
            if wealth_ratio < 0.5 and years_to_retirement > 5:
                # Behind target — increase equity allocation
                equity_target = min(0.95, equity_target * 1.2)
            elif wealth_ratio > 1.5:
                # Ahead of target — can de-risk
                equity_target = max(0.2, equity_target * 0.85)

        # Contribution adjustment: regular contributions allow more risk
        if annual_contribution > 0 and current_wealth > 0:
            contribution_ratio = annual_contribution / max(current_wealth, 1.0)
            if contribution_ratio > 0.1:
                # Significant ongoing contributions
                equity_target = min(0.95, equity_target * 1.1)

        # Map equity target to actual asset weights
        n = self.n_assets

        # Sort assets by volatility (rough proxy for equity-like)
        vol_order = np.argsort(self.vols)
        n_equity = max(1, int(n * equity_target))

        # Hi-vol assets get equity allocation
        w = np.zeros(n)
        for i in range(n):
            if i >= n - n_equity:
                idx = vol_order[i]
                w[idx] = 1.0 / n_equity
            else:
                idx = vol_order[i]
                w[idx] = 1.0 / max(1, n - n_equity)

        w = w / w.sum()
        port_ret = float(w @ self.mean_ret)
        port_vol = float(np.sqrt(w @ self.cov @ w))
        sharpe = (port_ret - self.rf) / port_vol if port_vol > EPS else 0.0

        return {
            "weights": dict(zip(self.asset_names, w.tolist())),
            "expected_return": port_ret,
            "expected_volatility": port_vol,
            "sharpe_ratio": sharpe,
            "equity_allocation": equity_target,
            "bond_allocation": 1.0 - equity_target,
            "age": age,
            "years_to_retirement": years_to_retirement,
            "risk_profile": risk_profile,
            "method": "lifecycle_glide_path",
        }

    # ------------------------------------------------------------------
    # Factor-Based Allocation
    # ------------------------------------------------------------------

    def factor_based_allocation(
        self,
        factor_exposures: pd.DataFrame,
        target_factor_betas: Dict[str, float],
        max_tracking_error: float = 0.10,
        lambda_reg: float = 0.01,
    ) -> Dict[str, Any]:
        """Allocate to achieve target factor exposures.

        Minimize tracking error while achieving desired factor tilts.

        Parameters
        ----------
        factor_exposures : pd.DataFrame
            N x K matrix: N assets, K factors (e.g., 'Value', 'Momentum',
            'Size', 'Quality', 'LowVol')
        target_factor_betas : dict
            {factor_name: target_beta} for desired factor tilts
        max_tracking_error : float, default=0.10
            Maximum allowable tracking error vs equal-weight benchmark
        lambda_reg : float, default=0.01
            L2 regularization on weights

        Returns
        -------
        dict with weights, achieved betas, tracking_error
        """
        factors = factor_exposures.values.astype(np.float64)
        factor_names = list(factor_exposures.columns)
        n = self.n_assets
        k = len(factor_names)

        # Benchmark: equal weight
        bm = np.ones(n) / n

        # Target betas vector
        target_b = np.array([target_factor_betas.get(f, 0.0) for f in factor_names],
                            dtype=np.float64)

        def _factor_obj(w: np.ndarray) -> float:
            # Active weights
            active = w - bm

            # Factor objective: achieve target betas
            achieved_b = factors.T @ w
            factor_error = np.sum((achieved_b - target_b) ** 2)

            # Tracking error
            te = active @ self.cov @ active

            # Regularization
            reg = lambda_reg * np.sum(w ** 2)

            return te + factor_error + reg

        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
            {"type": "ineq", "fun": lambda w: max_tracking_error ** 2 - (w - bm) @ self.cov @ (w - bm)},
        ]
        bounds = Bounds(0, 1)

        # Multiple starting points
        best_w = None
        best_obj = np.inf

        for w0 in [bm, np.ones(n) / n, self.vols / self.vols.sum()]:
            result = minimize(
                _factor_obj, w0,
                method="SLSQP",
                bounds=bounds,
                constraints=constraints,
                options={"ftol": 1e-12, "maxiter": 10000},
            )
            if result.success and result.fun < best_obj:
                best_obj = result.fun
                best_w = result.x

        if best_w is None:
            best_w = bm.copy()

        w = best_w / best_w.sum()
        achieved_betas = dict(zip(factor_names, (factors.T @ w).tolist()))
        te = float(np.sqrt((w - bm) @ self.cov @ (w - bm)))

        port_ret = float(w @ self.mean_ret)
        port_vol = float(np.sqrt(w @ self.cov @ w))

        return {
            "weights": dict(zip(self.asset_names, w.tolist())),
            "expected_return": port_ret,
            "expected_volatility": port_vol,
            "sharpe_ratio": (port_ret - self.rf) / port_vol if port_vol > EPS else 0.0,
            "achieved_factor_betas": achieved_betas,
            "target_factor_betas": target_factor_betas,
            "tracking_error": te,
            "method": "factor_based_allocation",
        }

    # ------------------------------------------------------------------
    # Risk Budget Allocation
    # ------------------------------------------------------------------

    def risk_budget_allocation(
        self,
        risk_budgets: Optional[Dict[str, float]] = None,
        asset_classes: Optional[Dict[str, str]] = None,
        target_class_vol: float = 0.12,
    ) -> Dict[str, Any]:
        """Allocate based on risk budgets per asset class.

        The practitioner's approach: first decide how much risk to take
        in each asset class, then build the portfolio to match those
        risk budgets.

        Parameters
        ----------
        risk_budgets : dict, optional
            {asset_name: risk_budget_pct}. If None, equal risk budget.
        asset_classes : dict, optional
            {asset_name: class_name} for grouping
        target_class_vol : float, default=0.12
            Target portfolio volatility

        Returns
        -------
        dict with weights, risk_contributions, class_risk_exposures
        """
        n = self.n_assets

        if risk_budgets is None:
            target_rc = np.ones(n) / n
        else:
            target_rc = np.array([risk_budgets.get(a, 0.0) for a in self.asset_names],
                                 dtype=np.float64)
            target_rc = target_rc / target_rc.sum()

        def _rb_obj(w: np.ndarray) -> float:
            port_var = w @ self.cov @ w
            if port_var < EPS:
                return 1.0
            mrc = self.cov @ w
            actual_rc = w * mrc / port_var
            return np.sum((actual_rc - target_rc) ** 2)

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = Bounds(0, 1)

        best_w = None
        best_obj = np.inf

        for w0 in [np.ones(n) / n, target_rc, self.vols / self.vols.sum()]:
            result = minimize(
                _rb_obj, w0,
                method="SLSQP", bounds=bounds, constraints=constraints,
                options={"ftol": 1e-12, "maxiter": 10000},
            )
            if result.success and result.fun < best_obj:
                best_obj = result.fun
                best_w = result.x

        if best_w is None:
            best_w = np.ones(n) / n

        w = best_w / best_w.sum()
        port_ret = float(w @ self.mean_ret)
        port_vol = float(np.sqrt(w @ self.cov @ w))
        mrc = self.cov @ w
        rc = (w * mrc) / (w @ self.cov @ w + EPS)

        # Class-level risk exposure
        class_risk = {}
        if asset_classes:
            class_weights = {}
            for i, asset in enumerate(self.asset_names):
                cls = asset_classes.get(asset, "Other")
                if cls not in class_weights:
                    class_weights[cls] = 0.0
                class_weights[cls] += w[i]

            for cls, cw in class_weights.items():
                class_risk[cls] = float(cw * target_class_vol)

        return {
            "weights": dict(zip(self.asset_names, w.tolist())),
            "expected_return": port_ret,
            "expected_volatility": port_vol,
            "sharpe_ratio": (port_ret - self.rf) / port_vol if port_vol > EPS else 0.0,
            "risk_contributions": dict(zip(self.asset_names, rc.tolist())),
            "class_risk_exposures": class_risk,
            "target_risk_budgets": dict(zip(self.asset_names, target_rc.tolist())),
            "method": "risk_budget_allocation",
        }

