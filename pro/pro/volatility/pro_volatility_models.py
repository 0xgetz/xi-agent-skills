
"""
Professional Volatility Models
================================
Amateurs see price. Pros see volatility.

Includes:
  - GARCHModels        : GARCH(1,1), EGARCH, GJR-GARCH
  - RealizedVolatility  : multiple vol estimators
  - VolatilityForecast  : HAR-RV, forecast combination
  - ImpliedVolatility   : BS implied vol, smile, VIX
  - VolatilitySurface   : SVI, interpolation, dynamics
  - VolatilityTargeting : scaling, risk parity

References:
  Bollerslev (1986) - GARCH
  Nelson (1991)     - EGARCH
  Glosten, Jagannathan & Runkle (1993) - GJR-GARCH
  Parkinson (1980)  - High-Low estimator
  Garman & Klass (1980)
  Rogers & Satchell (1991)
  Yang & Zhang (2000)
  Barndorff-Nielsen et al. (2008) - Realized kernel
  Corsi (2009)      - HAR-RV
  Gatheral (2004)   - SVI
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, List, Dict, Callable
from scipy.optimize import minimize, brentq
from scipy.stats import norm, chi2
from scipy.interpolate import RectBivariateSpline, interp1d
from dataclasses import dataclass, field


# ╔══════════════════════════════════════════════════════════════╗
# ║  1. GARCHModels                                              ║
# ╚══════════════════════════════════════════════════════════════╝

class GARCHModels:
    """
    GARCH family models for conditional volatility estimation.
    Supports GARCH(1,1), EGARCH(1,1), and GJR-GARCH(1,1).

    Fits via MLE (BFGS) and forecasts the volatility term structure.
    """

    def __init__(self, model_type: str = "garch"):
        """
        Parameters
        ----------
        model_type : str
            One of 'garch', 'egarch', 'gjrgarch'
        """
        assert model_type in ("garch", "egarch", "gjrgarch"), \
            f"Unknown model_type: {model_type}"
        self.model_type = model_type
        self.params_: Optional[np.ndarray] = None
        self.residuals_: Optional[np.ndarray] = None
        self.conditional_vol_: Optional[np.ndarray] = None
        self.llf_: float = -np.inf

    # ── Negative log-likelihood for GARCH(1,1) ──────────────────
    @staticmethod
    def _neg_ll_garch(theta: np.ndarray, r: np.ndarray) -> float:
        omega, alpha, beta = theta
        T = len(r)
        sigma2 = np.zeros(T)
        sigma2[0] = np.var(r)
        for t in range(1, T):
            sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]
        # avoid zero/negative variances
        sigma2 = np.maximum(sigma2, 1e-8)
        ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + r**2 / sigma2)
        return -ll / T  # average negative log-likelihood

    # ── Negative log-likelihood for EGARCH(1,1) ─────────────────
    @staticmethod
    def _neg_ll_egarch(theta: np.ndarray, r: np.ndarray) -> float:
        omega, alpha, beta, gamma = theta
        T = len(r)
        log_sigma2 = np.zeros(T)
        log_sigma2[0] = np.log(np.var(r))
        z = np.zeros(T)
        for t in range(1, T):
            z[t-1] = r[t-1] / np.sqrt(np.exp(log_sigma2[t-1]))
            log_sigma2[t] = (omega + beta * log_sigma2[t-1]
                             + alpha * (np.abs(z[t-1]) - np.sqrt(2/np.pi))
                             + gamma * z[t-1])
        sigma2 = np.exp(log_sigma2)
        sigma2 = np.maximum(sigma2, 1e-8)
        ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + r**2 / sigma2)
        return -ll / T

    # ── Negative log-likelihood for GJR-GARCH(1,1) ──────────────
    @staticmethod
    def _neg_ll_gjr(theta: np.ndarray, r: np.ndarray) -> float:
        omega, alpha, gamma, beta = theta
        T = len(r)
        sigma2 = np.zeros(T)
        sigma2[0] = np.var(r)
        for t in range(1, T):
            sigma2[t] = (omega + alpha * r[t-1]**2
                         + gamma * max(0, -r[t-1])**2
                         + beta * sigma2[t-1])
        sigma2 = np.maximum(sigma2, 1e-8)
        ll = -0.5 * np.sum(np.log(2 * np.pi * sigma2) + r**2 / sigma2)
        return -ll / T

    def fit(self, returns: np.ndarray) -> "GARCHModels":
        """
        Fit the GARCH model to a return series.

        Parameters
        ----------
        returns : np.ndarray
            1-D array of log returns.

        Returns
        -------
        self
        """
        r = np.asarray(returns, dtype=float).flatten()
        r = r - np.mean(r)  # demean

        if self.model_type == "garch":
            # omega, alpha, beta
            x0 = np.array([0.01 * np.var(r), 0.1, 0.8])
            bounds = [(1e-8, None), (1e-8, 1), (1e-8, 1)]
            cons = [{"type": "ineq", "fun": lambda x: 1 - x[1] - x[2]}]
            result = minimize(
                self._neg_ll_garch, x0, args=(r,),
                bounds=bounds, constraints=cons,
                method="SLSQP", options={"maxiter": 1000}
            )
            if not result.success:
                result = minimize(
                    self._neg_ll_garch, x0, args=(r,),
                    bounds=bounds, constraints=cons,
                    method="trust-constr", options={"maxiter": 2000}
                )
            self.params_ = result.x
            self.llf_ = -result.fun * len(r)
            # Recover conditional vol
            omega, alpha, beta = self.params_
            T = len(r)
            sigma2 = np.zeros(T)
            sigma2[0] = np.var(r)
            for t in range(1, T):
                sigma2[t] = omega + alpha * r[t-1]**2 + beta * sigma2[t-1]

        elif self.model_type == "egarch":
            x0 = np.array([-0.1, 0.1, 0.9, -0.05])
            bounds = [(None, None), (1e-8, None), (1e-8, 1), (None, None)]
            result = minimize(
                self._neg_ll_egarch, x0, args=(r,),
                bounds=bounds, method="L-BFGS-B", options={"maxiter": 1000}
            )
            self.params_ = result.x
            self.llf_ = -result.fun * len(r)
            omega, alpha, beta, gamma = self.params_
            T = len(r)
            log_sigma2 = np.zeros(T)
            log_sigma2[0] = np.log(np.var(r))
            z = np.zeros(T)
            for t in range(1, T):
                z[t-1] = r[t-1] / np.sqrt(np.exp(log_sigma2[t-1]))
                log_sigma2[t] = (omega + beta * log_sigma2[t-1]
                                 + alpha * (np.abs(z[t-1]) - np.sqrt(2/np.pi))
                                 + gamma * z[t-1])
            sigma2 = np.exp(log_sigma2)

        elif self.model_type == "gjrgarch":
            x0 = np.array([0.01 * np.var(r), 0.05, 0.1, 0.85])
            bounds = [(1e-8, None), (1e-8, 1), (1e-8, 1), (1e-8, 1)]
            result = minimize(
                self._neg_ll_gjr, x0, args=(r,),
                bounds=bounds, method="L-BFGS-B", options={"maxiter": 1000}
            )
            self.params_ = result.x
            self.llf_ = -result.fun * len(r)
            omega, alpha, gamma, beta = self.params_
            T = len(r)
            sigma2 = np.zeros(T)
            sigma2[0] = np.var(r)
            for t in range(1, T):
                sigma2[t] = (omega + alpha * r[t-1]**2
                             + gamma * max(0, -r[t-1])**2
                             + beta * sigma2[t-1])

        self.conditional_vol_ = np.sqrt(np.maximum(sigma2, 1e-12))
        self.residuals_ = r / self.conditional_vol_
        return self

    def forecast(self, steps: int = 10) -> np.ndarray:
        """
        Forecast conditional volatility for `steps` ahead.

        Returns
        -------
        np.ndarray
            Forecasted annualized volatility for each step.
        """
        if self.params_ is None:
            raise RuntimeError("Model not fitted yet.")
        r = self.residuals_  # use residuals storage, or re-use original
        last_sigma2 = self.conditional_vol_[-1]**2

        forecasts = np.zeros(steps)
        if self.model_type == "garch":
            omega, alpha, beta = self.params_
            # multi-step: E[sigma2_{t+k}] = omega + (alpha+beta) * E[sigma2_{t+k-1}]
            f = last_sigma2
            for i in range(steps):
                f = omega + (alpha + beta) * f
                forecasts[i] = np.sqrt(max(f, 1e-12))
        elif self.model_type == "egarch":
            omega, alpha, beta, gamma = self.params_
            # For EGARCH, in logs we approximate E[log(sigma2)] converging
            # to unconditional log-variance
            theta = alpha * np.sqrt(2/np.pi)  # E[|z| - sqrt(2/pi)] = 0
            uncond = omega / (1 - beta)
            f = np.log(self.conditional_vol_[-1]**2)
            for i in range(steps):
                f = omega + beta * f  # E[z] = 0, E[|z|-sqrt(2/pi)] = 0
                forecasts[i] = np.sqrt(max(np.exp(f), 1e-12))
        elif self.model_type == "gjrgarch":
            omega, alpha, gamma, beta = self.params_
            # GJR: leverage term contributes alpha + 0.5*gamma for symmetric innovation
            persist = alpha + 0.5 * gamma + beta
            f = last_sigma2
            for i in range(steps):
                f = omega + persist * f
                forecasts[i] = np.sqrt(max(f, 1e-12))
        return forecasts

    def term_structure(self, max_step: int = 252) -> pd.Series:
        """
        Volatility term structure: annualized vol forecast over horizon.

        Cumulative vol for horizon h: sqrt( (1/h) * sum_{i=1}^{h} f_i^2 )
        """
        f = self.forecast(max_step)
        cum_var = np.cumsum(f**2)
        h = np.arange(1, max_step + 1)
        cum_vol = np.sqrt(cum_var / h) * np.sqrt(252)
        return pd.Series(cum_vol, index=pd.RangeIndex(1, max_step + 1, name="horizon"))

    def summary(self) -> pd.Series:
        """Return fitted parameters and log-likelihood."""
        if self.params_ is None:
            return pd.Series({"status": "not fitted"})
        names = {
            "garch": ["omega", "alpha", "beta"],
            "egarch": ["omega", "alpha", "beta", "gamma"],
            "gjrgarch": ["omega", "alpha", "gamma", "beta"],
        }
        s = pd.Series(self.params_, index=names[self.model_type])
        s["log_likelihood"] = self.llf_
        s["aic"] = 2 * len(self.params_) - 2 * self.llf_
        s["bic"] = np.log(len(self.residuals_)) * len(self.params_) - 2 * self.llf_
        return s


# ╔══════════════════════════════════════════════════════════════╗
# ║  2. RealizedVolatility                                        ║
# ╚══════════════════════════════════════════════════════════════╝

class RealizedVolatility:
    """
    Compute realized volatility from OHLC / intraday data using multiple
    estimators. Each estimator provides a different trade-off between
    efficiency, bias, and robustness to market microstructure noise.

    References:
      Parkinson (1980)      - J. Business
      Garman & Klass (1980) - J. Business
      Rogers & Satchell (1991) - Mathematical Finance
      Yang & Zhang (2000)   - J. Business & Economic Statistics
      Barndorff-Nielsen et al. (2008) - Realized kernels
    """

    @staticmethod
    def daily_rv(prices: np.ndarray, time_bins: int = 1) -> float:
        """
        Daily realized volatility from intraday prices.

        Parameters
        ----------
        prices : np.ndarray
            Array of price observations sampled regularly.
        time_bins : int
            Number of intraday segments per day.

        Returns
        -------
        float
            Daily realized volatility (standard deviation of log returns).
        """
        log_p = np.log(np.asarray(prices, dtype=float))
        log_ret = np.diff(log_p)
        return float(np.sqrt(np.sum(log_ret**2)))

    @staticmethod
    def from_sampled(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                     open_: Optional[np.ndarray] = None,
                     estimator: str = "parkinson") -> pd.Series:
        """
        Compute a realized volatility series from a panel of OHLC data.

        Parameters
        ----------
        high, low, close : np.ndarray
            1-D arrays of price data (one row per period).
        open_ : np.ndarray, optional
            Opening prices (needed for Garman-Klass, Yang-Zhang).
        estimator : str
            One of: 'parkinson', 'garman_klass', 'rogers_satchell',
                    'yang_zhang', 'close_to_close'.

        Returns
        -------
        pd.Series of realized volatilities.
        """
        h, l, c = map(np.asarray, (high, low, close))
        h, l, c = [x.flatten().astype(float) for x in (h, l, c)]
        T = len(h)

        if estimator == "close_to_close":
            log_c = np.log(c)
            r = np.diff(log_c)
            rv = np.sqrt(np.concatenate([[np.nan], np.cumsum(r.reshape(-1, 1)**2, axis=1).sum(axis=1)]))
            return pd.Series(rv, name="rv_cc")

        log_h = np.log(h)
        log_l = np.log(l)
        log_c = np.log(c)
        if open_ is not None:
            log_o = np.log(np.asarray(open_, dtype=float).flatten())

        if estimator == "parkinson":
            # Parkinson (1980): sigma^2 = (1/(4*log(2))) * (H-L)^2
            variance = (1.0 / (4.0 * np.log(2))) * (log_h - log_l)**2
            rv = np.sqrt(np.maximum(variance, 1e-12))
            return pd.Series(rv, name="rv_parkinson")

        elif estimator == "garman_klass":
            # Garman-Klass (1980): sigma^2 = 0.5*(H-L)^2 - (2*log(2)-1)*(C-O)^2
            if open_ is None:
                raise ValueError("Open prices required for Garman-Klass.")
            variance = (0.5 * (log_h - log_l)**2
                        - (2 * np.log(2) - 1) * (log_c - log_o)**2)
            rv = np.sqrt(np.maximum(variance, 1e-12))
            return pd.Series(rv, name="rv_gk")

        elif estimator == "rogers_satchell":
            # Rogers-Satchell (1991): handles non-zero drift
            if open_ is None:
                raise ValueError("Open prices required for Rogers-Satchell.")
            variance = ((log_h - log_c) * (log_h - log_o)
                        + (log_l - log_c) * (log_l - log_o))
            rv = np.sqrt(np.maximum(variance, 1e-12))
            return pd.Series(rv, name="rv_rs")

        elif estimator == "yang_zhang":
            # Yang-Zhang (2000): unbiased for arbitrary drift
            # Uses overnight returns, open-to-close, and Rogers-Satchell
            if open_ is None:
                raise ValueError("Open prices required for Yang-Zhang.")
            k = 0.34 / (1.34 + (T + 1) / (T - 1))  # optimal weighting
            # Overnight variance (close to open)
            r_overnight = np.log(np.roll(open_, -1))[:-1] - log_c[:-1]
            sigma2_overnight = np.var(r_overnight, ddof=1)
            # Open-to-close variance
            r_oc = log_c - log_o
            sigma2_oc = np.var(r_oc, ddof=1)
            # Rogers-Satchell variance
            rs_var = ((log_h - log_c) * (log_h - log_o)
                      + (log_l - log_c) * (log_l - log_o))
            sigma2_rs = np.nanmean(rs_var)
            # Combine
            sigma2 = sigma2_overnight + k * sigma2_oc + (1 - k) * sigma2_rs
            rv = np.full(T, np.sqrt(max(sigma2, 1e-12)))
            return pd.Series(rv, name="rv_yz")

        else:
            raise ValueError(f"Unknown estimator: {estimator}")

    @staticmethod
    def parkinson(high: np.ndarray, low: np.ndarray) -> np.ndarray:
        """Parkinson (1980) extreme-value volatility estimator."""
        h, l = map(np.asarray, (high, low))
        log_r = np.log(h / l)
        return np.sqrt((1.0 / (4.0 * np.log(2))) * log_r**2)

    @staticmethod
    def garman_klass(open_: np.ndarray, high: np.ndarray,
                     low: np.ndarray, close: np.ndarray) -> np.ndarray:
        """Garman-Klass (1980) OHLC volatility estimator."""
        o, h, l, c = [np.log(np.asarray(x, dtype=float))
                      for x in (open_, high, low, close)]
        v = 0.5 * (h - l)**2 - (2 * np.log(2) - 1) * (c - o)**2
        return np.sqrt(np.maximum(v, 1e-12))

    @staticmethod
    def rogers_satchell(open_: np.ndarray, high: np.ndarray,
                        low: np.ndarray, close: np.ndarray) -> np.ndarray:
        """Rogers-Satchell (1991) drift-independent estimator."""
        o, h, l, c = [np.log(np.asarray(x, dtype=float))
                      for x in (open_, high, low, close)]
        v = (h - c) * (h - o) + (l - c) * (l - o)
        return np.sqrt(np.maximum(v, 1e-12))

    @staticmethod
    def yang_zhang(open_: np.ndarray, high: np.ndarray,
                   low: np.ndarray, close: np.ndarray) -> np.ndarray:
        """Yang-Zhang (2000) unbiased estimator with minimal MSE."""
        o, h, l, c = [np.asarray(x, dtype=float) for x in (open_, high, low, close)]
        T = len(c)
        k = 0.34 / (1.34 + (T + 1) / (T - 1))
        r_overnight = np.log(o[1:] / c[:-1])
        r_oc = np.log(c / o)
        sigma2_ov = np.nanvar(r_overnight, ddof=1)
        sigma2_oc = np.nanvar(r_oc, ddof=1)
        # RS component
        log_h, log_l, log_o, log_c = map(np.log, (h, l, o, c))
        rs_v = (log_h - log_c) * (log_h - log_o) + (log_l - log_c) * (log_l - log_o)
        sigma2_rs = np.nanmean(np.maximum(rs_v, 0))
        sigma2 = sigma2_ov + k * sigma2_oc + (1 - k) * sigma2_rs
        return np.full(T, np.sqrt(max(sigma2, 1e-12)))

    @staticmethod
    def realized_kernel(prices: np.ndarray, max_lag: int = 20,
                        kernel: str = "bartlett") -> float:
        """
        Realized kernel (Barndorff-Nielsen et al., 2008).
        Robust to market microstructure noise.

        Parameters
        ----------
        prices : np.ndarray
            High-frequency price observations.
        max_lag : int
            Maximum lag for autocovariance terms.
        kernel : str
            'bartlett', 'parzen', or 'tukey_hanning'

        Returns
        -------
        float
            Realized kernel volatility estimate.
        """
        log_p = np.log(np.asarray(prices, dtype=float))
        r = np.diff(log_p)  # tick returns
        n = len(r)
        # Base realized variance
        rv = np.sum(r**2)
        # Weighted autocovariances
        gamma_0 = rv
        kernel_weights = np.zeros(max_lag + 1)
        kernel_weights[0] = 1.0
        for h in range(1, max_lag + 1):
            x = h / max_lag
            if kernel == "bartlett":
                w = 1 - x
            elif kernel == "parzen":
                if x <= 0.5:
                    w = 1 - 6 * x**2 + 6 * x**3
                else:
                    w = 2 * (1 - x)**3
            elif kernel == "tukey_hanning":
                w = (1 + np.cos(np.pi * x)) / 2
            else:
                raise ValueError(f"Unknown kernel: {kernel}")
            kernel_weights[h] = w

        gamma_h = np.zeros(max_lag + 1)
        for h in range(1, max_lag + 1):
            gamma_h[h] = np.sum(r[:n - h] * r[h:])

        rk = kernel_weights[0] * gamma_0 + 2 * np.sum(kernel_weights[1:] * gamma_h[1:])
        return float(np.sqrt(max(rk, 1e-12)))


# ╔══════════════════════════════════════════════════════════════╗
# ║  3. VolatilityForecast                                        ║
# ╚══════════════════════════════════════════════════════════════╝

class VolatilityForecast:
    """
    HAR-RV model of Corsi (2009) for realized volatility forecasting.

    The Heterogeneous Autoregressive model captures the cascade of
    trading horizons (daily, weekly, monthly) influencing volatility.
    """

    def __init__(self):
        self.coef_: Optional[np.ndarray] = None
        self.residuals_: Optional[np.ndarray] = None
        self.fitted_: Optional[np.ndarray] = None
        self.rv_series_: Optional[pd.Series] = None

    def _build_regressors(self, rv: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """
        Build HAR-RV regressors.
        rv_{t+1} = beta0 + beta1*rv_d_t + beta2*rv_w_t + beta3*rv_m_t + eps

        rv_d = log of daily RV
        rv_w = avg log RV over past 5 days
        rv_m = avg log RV over past 22 days

        Returns (X, y) where y is log(rv_{t+1})
        """
        log_rv = np.log(np.maximum(rv, 1e-12))
        # Compute HAR components
        rv_d = log_rv
        rv_w = pd.Series(log_rv).rolling(5, min_periods=1).mean().values
        rv_m = pd.Series(log_rv).rolling(22, min_periods=1).mean().values

        # Build X matrix with intercept, lag by 1
        # X: [1, rv_d_t, rv_w_t, rv_m_t]
        # y: log_rv_{t+1}
        X = np.column_stack([np.ones(len(rv)), rv_d, rv_w, rv_m])
        y = log_rv
        # Shift so X_t predicts y_{t+1}
        X = X[:-1]
        y = y[1:]
        return X, y

    def fit(self, rv: np.ndarray) -> "VolatilityForecast":
        """
        Fit HAR-RV model via OLS.

        Parameters
        ----------
        rv : np.ndarray
            Realized volatility series.
        """
        rv = np.asarray(rv, dtype=float).flatten()
        self.rv_series_ = pd.Series(rv, name="rv")
        X, y = self._build_regressors(rv)
        # OLS via normal equations
        self.coef_ = np.linalg.lstsq(X, y, rcond=None)[0]
        self.fitted_ = X @ self.coef_
        self.residuals_ = y - self.fitted_
        return self

    def predict(self, rv_window: np.ndarray, steps: int = 1) -> np.ndarray:
        """
        Predict future realized volatility.

        Parameters
        ----------
        rv_window : np.ndarray
            Recent RV values (at least 22 for monthly component).
        steps : int
            Number of steps ahead.

        Returns
        -------
        np.ndarray
            Predicted RV (not log).
        """
        if self.coef_ is None:
            raise RuntimeError("Model not fitted yet.")
        rv = np.asarray(rv_window, dtype=float).flatten()
        b0, b1, b2, b3 = self.coef_
        preds = []
        for _ in range(steps):
            rv_d = np.log(max(rv[-1], 1e-12))
            rv_w = np.log(max(np.mean(rv[-5:]), 1e-12)) if len(rv) >= 5 else rv_d
            rv_m = np.log(max(np.mean(rv[-22:]), 1e-12)) if len(rv) >= 22 else rv_w
            log_pred = b0 + b1 * rv_d + b2 * rv_w + b3 * rv_m
            pred = np.exp(log_pred)
            preds.append(pred)
            # Append prediction to window for multi-step
            rv = np.append(rv, pred)
        return np.array(preds)

    @staticmethod
    def forecast_combination(forecasts: Dict[str, np.ndarray],
                             method: str = "equal") -> np.ndarray:
        """
        Combine multiple volatility forecasts.

        Parameters
        ----------
        forecasts : dict of str -> np.ndarray
            Named forecast arrays (same length).
        method : str
            'equal' - equal weights
            'inverse_mse' - weighted by inverse MSE
            'inverse_var' - weighted by inverse variance
            'median' - median across models

        Returns
        -------
        np.ndarray
            Combined forecast.
        """
        names = list(forecasts.keys())
        arr = np.column_stack([forecasts[n] for n in names])
        if method == "equal":
            w = np.ones(len(names)) / len(names)
        elif method in ("inverse_mse", "inverse_var"):
            errors = np.zeros(len(names))
            for i, n in enumerate(names):
                if method == "inverse_mse":
                    errors[i] = np.nanmean(arr[:, i]**2)  # placeholder MSE
                else:
                    errors[i] = np.nanvar(arr[:, i])
            w = 1.0 / (errors + 1e-12)
            w /= w.sum()
        elif method == "median":
            return np.nanmedian(arr, axis=1)
        else:
            raise ValueError(f"Unknown combination method: {method}")
        return arr @ w

    @staticmethod
    def volatility_cone(rv_series: np.ndarray,
                        horizons: List[int] = None) -> pd.DataFrame:
        """
        Volatility cone (term structure of volatility quantiles).

        For each horizon h, resample the RV series into overlapping
        windows of length h and compute mean, median, and quantiles
        of the annualized volatility.

        Parameters
        ----------
        rv_series : np.ndarray
            Daily realized volatility series (daily values).
        horizons : list of int
            Horizons in days.

        Returns
        -------
        pd.DataFrame indexed by horizon with columns:
            mean, median, q05, q25, q75, q95
        """
        if horizons is None:
            horizons = [1, 5, 10, 21, 42, 63, 126, 252]
        rv = np.asarray(rv_series, dtype=float).flatten()
        results = {}
        for h in horizons:
            ann_factor = np.sqrt(252 / h)
            vols = []
            for i in range(len(rv) - h + 1):
                # Cumulative RV over h days
                cum_var = np.sum(rv[i:i+h]**2)
                vols.append(np.sqrt(cum_var) * np.sqrt(252))
            vols = np.array(vols)
            results[h] = {
                "mean": np.nanmean(vols),
                "median": np.nanmedian(vols),
                "q05": np.nanpercentile(vols, 5),
                "q25": np.nanpercentile(vols, 25),
                "q75": np.nanpercentile(vols, 75),
                "q95": np.nanpercentile(vols, 95),
            }
        df = pd.DataFrame(results).T
        df.index.name = "horizon_days"
        return df


# ╔══════════════════════════════════════════════════════════════╗
# ║  4. ImpliedVolatility                                         ║
# ╚══════════════════════════════════════════════════════════════╝

class ImpliedVolatility:
    """
    Black-Scholes implied volatility and related calculations.

    References:
      Black & Scholes (1973)
      Gatheral (2004) - The Volatility Surface
    """

    N = norm.cdf
    N_prime = norm.pdf

    @staticmethod
    def _d1(S: float, K: float, T: float, r: float, sigma: float,
            q: float = 0.0) -> float:
        """d1 in Black-Scholes."""
        return (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / (sigma * np.sqrt(T))

    @staticmethod
    def _d2(d1: float, sigma: float, T: float) -> float:
        """d2 in Black-Scholes."""
        return d1 - sigma * np.sqrt(T)

    @classmethod
    def bs_price(cls, S: float, K: float, T: float, r: float, sigma: float,
                 q: float = 0.0, option_type: str = "call") -> float:
        """Black-Scholes option price."""
        d1 = cls._d1(S, K, T, r, sigma, q)
        d2 = cls._d2(d1, sigma, T)
        if option_type == "call":
            return S * np.exp(-q * T) * cls.N(d1) - K * np.exp(-r * T) * cls.N(d2)
        else:
            return K * np.exp(-r * T) * cls.N(-d2) - S * np.exp(-q * T) * cls.N(-d1)

    @classmethod
    def implied_vol(cls, price: float, S: float, K: float, T: float, r: float,
                    q: float = 0.0, option_type: str = "call",
                    initial_guess: float = 0.3) -> float:
        """
        Compute Black-Scholes implied volatility via Newton-Raphson + bisection.

        Parameters
        ----------
        price : float
            Market option price.
        S : float
            Spot price.
        K : float
            Strike price.
        T : float
            Time to expiry (years).
        r : float
            Risk-free rate.
        q : float
            Dividend yield.
        option_type : str
            'call' or 'put'.
        initial_guess : float
            Starting volatility.

        Returns
        -------
        float
            Implied volatility.
        """
        # Objective: find sigma such that bs_price = price
        f = lambda s: (cls.bs_price(S, K, T, r, s, q, option_type) - price)
        # Check for arbitrage
        intrinsic = max(0, (S - K) if option_type == "call" else (K - S))
        if price < intrinsic - 1e-8:
            return np.nan
        # Bisection to bracket root
        s_low, s_high = 0.001, 5.0
        f_low, f_high = f(s_low), f(s_high)
        # If price is at boundary, return NaN
        if f_low > 0:
            return 0.001  # essentially zero vol
        if f_high < 0:
            return np.nan

        # Newton-Raphson with bisection fallback
        sigma = initial_guess
        for _ in range(200):
            d1 = cls._d1(S, K, T, r, sigma, q)
            vega = S * np.sqrt(T) * cls.N_prime(d1) * np.exp(-q * T)
            if abs(vega) < 1e-12:
                break
            diff = f(sigma)
            sigma_new = sigma - diff / vega
            # Newton step might overshoot; bisection if outside bracket
            if sigma_new <= 0 or sigma_new > 5:
                sigma_new = (s_low + s_high) / 2
            # Update bracket
            f_new = f(sigma_new) if sigma_new != 0 else 0
            if sigma_new > sigma:
                s_high = sigma_new
            else:
                s_low = sigma_new
            sigma = sigma_new
            if abs(diff) < 1e-8:
                break
        return max(sigma, 0.001)

    @classmethod
    def volatility_smile(cls, S: float, strikes: np.ndarray, T: float, r: float,
                         option_prices: np.ndarray, q: float = 0.0,
                         option_type: str = "call") -> pd.Series:
        """
        Compute implied volatilities across strikes (vol smile).

        Returns
        -------
        pd.Series indexed by strike.
        """
        ivs = []
        for K, p in zip(strikes, option_prices):
            iv = cls.implied_vol(p, S, K, T, r, q, option_type)
            ivs.append(iv)
        return pd.Series(ivs, index=strikes, name="implied_vol")

    @classmethod
    def volatility_skew(cls, S: float, strikes: np.ndarray, T: float, r: float,
                        option_prices: np.ndarray, q: float = 0.0,
                        option_type: str = "call") -> float:
        """
        Volatility skew: measure of slope of smile at the money.
        Returns (IV(K=90% of ATM) - IV(K=110% of ATM)).
        """
        iv_series = cls.volatility_smile(S, strikes, T, r, option_prices, q, option_type)
        atm_idx = np.argmin(np.abs(strikes - S))
        # Find 90% and 110% strikes
        k_low = S * 0.9
        k_high = S * 1.1
        iv_low = np.interp(k_low, strikes, iv_series.values)
        iv_high = np.interp(k_high, strikes, iv_series.values)
        return iv_low - iv_high

    @classmethod
    def term_structure(cls, S: float, K: float, expiries: np.ndarray,
                       r: float, option_prices: np.ndarray, q: float = 0.0,
                       option_type: str = "call") -> pd.Series:
        """Implied volatility across maturities."""
        ivs = [cls.implied_vol(p, S, K, T, r, q, option_type)
               for p, T in zip(option_prices, expiries)]
        return pd.Series(ivs, index=expiries, name="implied_vol")

    @staticmethod
    def vix_style(options_data: pd.DataFrame) -> float:
        """
        VIX-style implied volatility calculation.

        Parameters
        ----------
        options_data : pd.DataFrame
            Must have columns:
            'strike', 'call_price', 'put_price', 'expiry',
            'forward', 'rate'
            Uses out-of-the-money options (calls above forward, puts below).
            At least 2 strikes required.

        Returns
        -------
        float
            30-day implied volatility index (annualized, in %).
        """
        # Per CBOE VIX white paper
        df = options_data.copy()
        # Determine forward price from at-the-money put-call parity
        df["mid"] = (df["call_price"] + df["put_price"]) / 2
        atm_idx = df["mid"].idxmin()
        F = df.loc[atm_idx, "strike"] + np.exp(df.loc[atm_idx, "rate"]
                                                * df.loc[atm_idx, "expiry"]) * (
            df.loc[atm_idx, "call_price"] - df.loc[atm_idx, "put_price"])
        # Determine ATM strike = highest strike below forward
        below = df[df["strike"] < F]
        if len(below) == 0:
            K0 = df["strike"].min()
        else:
            K0 = below["strike"].max()
        # Select OTM options
        calls_otm = df[(df["strike"] >= K0) & (df["call_price"] > 0)].copy()
        puts_otm = df[(df["strike"] <= K0) & (df["put_price"] > 0)].copy()
        # Use put prices for strikes <= K0, call prices for strikes >= K0
        selected = pd.concat([
            puts_otm[["strike", "put_price", "expiry", "rate"]].rename(
                columns={"put_price": "contrib"}),
            calls_otm[["strike", "call_price", "expiry", "rate"]].rename(
                columns={"call_price": "contrib"})
        ])
        selected = selected.drop_duplicates(subset="strike")
        selected = selected.sort_values("strike")
        # Compute delta K
        selected["delta_K"] = np.zeros(len(selected))
        for i in range(len(selected)):
            if i == 0:
                selected.iloc[i, selected.columns.get_loc("delta_K")] = (
                    selected.iloc[i + 1]["strike"] - selected.iloc[i]["strike"])
            elif i == len(selected) - 1:
                selected.iloc[i, selected.columns.get_loc("delta_K")] = (
                    selected.iloc[i]["strike"] - selected.iloc[i - 1]["strike"])
            else:
                selected.iloc[i, selected.columns.get_loc("delta_K")] = (
                    (selected.iloc[i + 1]["strike"] - selected.iloc[i - 1]["strike"]) / 2)
        # Compute contribution
        T = df["expiry"].iloc[0]
        R = df["rate"].iloc[0]
        selected["contrib"] = (selected["delta_K"] / selected["strike"]**2
                               * np.exp(R * T) * selected["contrib"])
        sigma2 = (2 / T) * selected["contrib"].sum() - (1 / T) * (F / K0 - 1)**2
        return float(np.sqrt(max(sigma2, 1e-12)) * 100)


# ╔══════════════════════════════════════════════════════════════╗
# ║  5. VolatilitySurface                                         ║
# ╚══════════════════════════════════════════════════════════════╝

class VolatilitySurface:
    """
    Volatility surface interpolation and SVI parameterization.

    References:
      Gatheral (2004) - The Volatility Surface
      Gatheral & Jacquier (2014) - Arbitrage-free SVI
    """

    def __init__(self):
        self.strikes_: Optional[np.ndarray] = None
        self.expiries_: Optional[np.ndarray] = None
        self.iv_matrix_: Optional[np.ndarray] = None
        self.spline_: Optional[RectBivariateSpline] = None
        self.svi_params_: Dict[float, Tuple] = {}  # expiry -> (a, b, rho, m, sigma)

    def build(self, strikes: np.ndarray, expiries: np.ndarray,
              iv_matrix: np.ndarray) -> "VolatilitySurface":
        """
        Build the volatility surface from observed implied vols.

        Parameters
        ----------
        strikes : np.ndarray
            1-D array of strike prices.
        expiries : np.ndarray
            1-D array of expiries (years). Must be sorted.
        iv_matrix : np.ndarray
            2-D array of shape (len(expiries), len(strikes)).
        """
        self.strikes_ = np.asarray(strikes, dtype=float).flatten()
        self.expiries_ = np.asarray(expiries, dtype=float).flatten()
        self.iv_matrix_ = np.asarray(iv_matrix, dtype=float)
        # Sort expiries and sync rows
        sort_idx = np.argsort(self.expiries_)
        self.expiries_ = self.expiries_[sort_idx]
        self.iv_matrix_ = self.iv_matrix_[sort_idx]
        self.spline_ = RectBivariateSpline(self.expiries_, self.strikes_,
                                            self.iv_matrix_)
        return self

    def interpolate(self, expiry: float, strike: float) -> float:
        """Get interpolated implied volatility at (expiry, strike)."""
        if self.spline_ is None:
            raise RuntimeError("Surface not built yet.")
        return float(self.spline_(expiry, strike)[0, 0])

    def interpolate_grid(self, expiries: np.ndarray,
                         strikes: np.ndarray) -> np.ndarray:
        """Get interpolated IV over a grid of expiries x strikes."""
        if self.spline_ is None:
            raise RuntimeError("Surface not built yet.")
        return self.spline_(expiries, strikes)

    # ── SVI parameterization (Gatheral) ─────────────────────────

    @staticmethod
    def svi_raw(k: np.ndarray, a: float, b: float, rho: float,
                m: float, sigma: float) -> np.ndarray:
        """
        Raw SVI parameterization: total implied variance w(k) = a + b*(rho*(k-m) + sqrt((k-m)^2 + sigma^2))

        Parameters
        ----------
        k : np.ndarray
            Log-strike (log(K/F)).
        a, b, rho, m, sigma : float
            SVI parameters.

        Returns
        -------
        np.ndarray
            Total implied variance (w) at each log-strike.
        """
        return a + b * (rho * (k - m) + np.sqrt((k - m)**2 + sigma**2))

    def fit_svi(self, log_strikes: np.ndarray, total_var: np.ndarray,
                expiry: float = 1.0) -> Tuple[float, ...]:
        """
        Fit SVI parameters for a given expiry slice.

        Parameters
        ----------
        log_strikes : np.ndarray
            Log-moneyness values k = log(K/F).
        total_var : np.ndarray
            Total implied variance w = sigma_BS^2 * T.

        Returns
        -------
        tuple
            (a, b, rho, m, sigma)
        """
        k = np.asarray(log_strikes, dtype=float).flatten()
        w = np.asarray(total_var, dtype=float).flatten()

        def svi_err(params):
            a, b, rho, m, sigma = params
            # Constraints: b >= 0, sigma > 0, |rho| < 1
            if b < 0 or sigma <= 0 or abs(rho) >= 1:
                return 1e10
            w_hat = self.svi_raw(k, a, b, rho, m, sigma)
            return np.nanmean((w - w_hat)**2)

        # Multiple starting points
        best_result = None
        best_err = np.inf
        for _ in range(5):
            x0 = np.array([
                np.nanmean(w) * 0.5,  # a
                0.1 + 0.3 * np.random.random(),  # b
                -0.5 + np.random.random(),  # rho
                np.random.randn() * 0.1,  # m
                0.05 + 0.2 * np.random.random(),  # sigma
            ])
            bounds = [(0, None), (0, None), (-0.999, 0.999),
                      (None, None), (1e-6, None)]
            result = minimize(svi_err, x0, bounds=bounds,
                              method="L-BFGS-B", options={"maxiter": 500})
            if result.fun < best_err:
                best_err = result.fun
                best_result = result.x

        params = tuple(best_result) if best_result is not None else (0, 0.1, 0, 0, 0.2)
        self.svi_params_[expiry] = params
        return params

    def surface_dynamics(self, expiry1: float, expiry2: float) -> Dict[str, float]:
        """
        Measure surface dynamics between two expiry slices.

        Returns
        -------
        dict with keys:
            'atm_vol_short', 'atm_vol_long',
            'skew_short', 'skew_long',
            'steepening' (difference in atm vol),
            'flattening' (-steepening),
            'twist' (difference in skew)
        """
        if self.spline_ is None:
            raise RuntimeError("Surface not built yet.")

        atm_strike = self.strikes_[len(self.strikes_) // 2]

        iv_s = self.interpolate(expiry1, atm_strike)
        iv_l = self.interpolate(expiry2, atm_strike)

        # Skew at 90/110 ATM
        iv_s_low = self.interpolate(expiry1, atm_strike * 0.9)
        iv_s_high = self.interpolate(expiry1, atm_strike * 1.1)
        skew_s = iv_s_low - iv_s_high

        iv_l_low = self.interpolate(expiry2, atm_strike * 0.9)
        iv_l_high = self.interpolate(expiry2, atm_strike * 1.1)
        skew_l = iv_l_low - iv_l_high

        return {
            "atm_vol_short": float(iv_s),
            "atm_vol_long": float(iv_l),
            "skew_short": float(skew_s),
            "skew_long": float(skew_l),
            "steepening": float(iv_l - iv_s),
            "flattening": float(iv_s - iv_l),
            "twist": float(skew_l - skew_s),
        }


# ╔══════════════════════════════════════════════════════════════╗
# ║  6. VolatilityTargeting                                       ║
# ╚══════════════════════════════════════════════════════════════╝

class VolatilityTargeting:
    """
    Scale positions and portfolios to target a specific volatility level.

    Core idea: vol-targeting delivers a smoother equity curve with
    better risk-adjusted returns by reducing leverage when vol is
    high and increasing it when vol is low.
    """

    def __init__(self, target_vol: float = 0.20,
                 estimation_window: int = 21,
                 min_leverage: float = 0.0,
                 max_leverage: float = 5.0,
                 vol_lookback: int = 21):
        """
        Parameters
        ----------
        target_vol : float
            Target annualized volatility (e.g. 0.20 = 20%).
        estimation_window : int
            Rolling window for volatility estimation (days).
        min_leverage : float
            Minimum leverage (floor).
        max_leverage : float
            Maximum leverage (cap).
        vol_lookback : int
            Lookback period for realized vol computation.
        """
        self.target_vol = target_vol
        self.estimation_window = estimation_window
        self.min_leverage = min_leverage
        self.max_leverage = max_leverage
        self.vol_lookback = vol_lookback

    def scaling_factor(self, returns: np.ndarray) -> np.ndarray:
        """
        Compute the volatility scaling factor for each period.

        scaling_t = target_vol / realized_vol_t * sqrt(252)

        Returns
        -------
        np.ndarray
            Leverage multiplier for each period (NaN for first vol_lookback-1).
        """
        r = np.asarray(returns, dtype=float).flatten()
        # Rolling realized vol
        rv = pd.Series(r).rolling(self.vol_lookback).std(ddof=1) * np.sqrt(252)
        rv = rv.values
        scaling = self.target_vol / np.maximum(rv, 1e-8)
        # Clip leverage
        scaling = np.clip(scaling, self.min_leverage, self.max_leverage)
        scaling[:self.vol_lookback - 1] = np.nan
        return scaling

    def scale_positions(self, returns: np.ndarray,
                        positions: np.ndarray) -> np.ndarray:
        """
        Scale position sizes to target vol.

        Parameters
        ----------
        returns : np.ndarray
            Asset return series (1-D).
        positions : np.ndarray
            Position sizes (e.g., number of shares, notional).

        Returns
        -------
        np.ndarray
            Vol-targeted position sizes.
        """
        scaling = self.scaling_factor(returns)
        return positions * scaling

    @staticmethod
    def dynamic_leverage(returns: np.ndarray,
                         target_annualized_vol: float = 0.20,
                         vol_lookback: int = 21,
                         smoothing: float = 0.05) -> pd.Series:
        """
        Dynamic leverage adjustment with exponential smoothing.

        Leverage_t = (1 - smoothing) * leverage_{t-1}
                     + smoothing * (target_vol / current_vol)

        Parameters
        ----------
        returns : np.ndarray
            Return series.
        target_annualized_vol : float
            Target annualized vol (e.g. 0.20).
        vol_lookback : int
            Window for vol estimation.
        smoothing : float
            Exponential smoothing factor.

        Returns
        -------
        pd.Series
            Leverage time series.
        """
        r = np.asarray(returns, dtype=float).flatten()
        # Rolling vol
        rv = pd.Series(r).rolling(vol_lookback).std(ddof=1) * np.sqrt(252)
        raw_leverage = target_annualized_vol / np.maximum(rv.values, 1e-8)
        # Smooth
        smooth_leverage = np.full_like(raw_leverage, np.nan)
        smooth_leverage[vol_lookback] = raw_leverage[vol_lookback]
        for t in range(vol_lookback + 1, len(raw_leverage)):
            smooth_leverage[t] = (
                (1 - smoothing) * smooth_leverage[t - 1]
                + smoothing * raw_leverage[t])
        return pd.Series(smooth_leverage, name="leverage")

    @staticmethod
    def vol_risk_parity(cov_matrix: np.ndarray,
                        target_vol: float = 0.15) -> np.ndarray:
        """
        Volatility risk parity: allocate so each asset contributes
        equally to portfolio volatility.

        Parameters
        ----------
        cov_matrix : np.ndarray
            Covariance matrix of asset returns.
        target_vol : float
            Target portfolio volatility.

        Returns
        -------
        np.ndarray
            Risk parity weights.
        """
        n = cov_matrix.shape[0]
        # Marginal risk contributions: MRC_i = (Sigma @ w)_i / sqrt(w' @ Sigma @ w)
        # Vol parity: w_i * MRC_i = target / n for all i

        # Use Newton-style optimization: minimize sum of squared deviations
        # from equal risk contribution
        def risk_budget_objective(w):
            w = np.asarray(w)
            w = w / np.sum(w)  # normalize
            port_var = w @ cov_matrix @ w
            port_vol = np.sqrt(max(port_var, 1e-12))
            mrc = (cov_matrix @ w) / port_vol
            rc = w * mrc  # risk contributions
            target_rc = port_vol / n
            return np.sum((rc - target_rc)**2)

        x0 = np.ones(n) / n
        bounds = [(0, 1)] * n
        cons = [{"type": "eq", "fun": lambda x: np.sum(x) - 1}]
        result = minimize(risk_budget_objective, x0, bounds=bounds,
                          constraints=cons, method="SLSQP",
                          options={"maxiter": 1000})
        w = result.x
        # Scale to target vol
        w = w / np.sum(w)
        port_vol = np.sqrt(w @ cov_matrix @ w)
        if port_vol > 0:
            w = w * (target_vol / port_vol)
        return w


# ╔══════════════════════════════════════════════════════════════╗
# ║  Quick Self-Test                                              ║
# ╚══════════════════════════════════════════════════════════════╝

def _demo():
    """Minimal demonstration of the module."""
    print("=" * 60)
    print("Volatility Models Demo")
    print("=" * 60)

    # --- GARCH ---
    np.random.seed(42)
    T = 500
    returns = np.random.randn(T) * 0.01

    for name in ("garch", "egarch", "gjrgarch"):
        m = GARCHModels(model_type=name)
        m.fit(returns)
        print(f"\n{name.upper()} summary:")
        print(m.summary().round(6))
        f = m.forecast(10)
        print(f"  10-step vol forecast (daily): last={f[-1]:.6f}")

    # --- Realized Volatility ---
    print("\n--- Realized Volatility ---")
    np.random.seed(99)
    n = 252
    o = np.cumsum(np.random.randn(n) * 0.005) + 100
    h = o * (1 + np.abs(np.random.randn(n)) * 0.01)
    l = o * (1 - np.abs(np.random.randn(n)) * 0.01)
    c = o * (1 + np.random.randn(n) * 0.005)
    rv = RealizedVolatility()
    for est in ("parkinson", "garman_klass", "rogers_satchell", "yang_zhang"):
        s = rv.from_sampled(h, l, c, o, estimator=est)
        print(f"  {est:20s}: mean={s.mean():.6f}, last={s.iloc[-1]:.6f}")

    # Realized kernel
    prices = 100 + np.cumsum(np.random.randn(1000) * 0.01)
    rk = rv.realized_kernel(prices)
    print(f"  realized_kernel        : {rk:.6f}")

    # --- Volatility Forecast ---
    print("\n--- HAR-RV Forecast ---")
    vf = VolatilityForecast()
    rv_series = 0.01 + np.abs(np.random.randn(500) * 0.003)
    vf.fit(rv_series)
    pred = vf.predict(rv_series[-30:], steps=5)
    print(f"  5-step HAR-RV forecast: {pred.round(6)}")

    # Volatility cone
    cone = vf.volatility_cone(rv_series)
    print("  Volatility cone (mean):")
    print(f"    {cone['mean'].round(4).to_dict()}")

    # --- Implied Volatility ---
    print("\n--- Implied Volatility ---")
    S, K, T, r = 100, 100, 0.5, 0.05
    true_sigma = 0.30
    price = ImpliedVolatility.bs_price(S, K, T, r, true_sigma)
    iv = ImpliedVolatility.implied_vol(price, S, K, T, r)
    print(f"  True sigma={true_sigma}, BS price={price:.4f}, IV={iv:.4f}")

    # Smile
    strikes = np.linspace(80, 120, 9)
    prices = [ImpliedVolatility.bs_price(S, k, T, r, true_sigma) for k in strikes]
    smile = ImpliedVolatility.volatility_smile(S, strikes, T, r, np.array(prices))
    print(f"  Smile: min IV={smile.min():.4f}, max IV={smile.max():.4f}")

    # --- Volatility Surface ---
    print("\n--- Volatility Surface ---")
    vs = VolatilitySurface()
    expiries = np.array([0.1, 0.3, 0.6, 1.0])
    svi_strikes = np.linspace(80, 120, 10)
    # Generate fake surface
    X, Y = np.meshgrid(expiries, svi_strikes, indexing='ij')
    iv_mat = 0.2 + 0.1 * X + 0.05 * (Y - 100) / 100
    vs.build(svi_strikes, expiries, iv_mat)
    iv_atm = vs.interpolate(0.5, 100)
    print(f"  Interpolated IV at (0.5yr, 100 strike) = {iv_atm:.4f}")

    # SVI
    k_vals = np.linspace(-1, 1, 20)
    w_target = 0.04 + 0.2 * (0.3 * k_vals + np.sqrt(k_vals**2 + 0.1**2))
    svi_params = vs.fit_svi(k_vals, w_target)
    print(f"  SVI params (a,b,rho,m,sigma): {np.round(svi_params, 4)}")

    # Surface dynamics
    dyn = vs.surface_dynamics(0.1, 1.0)
    print(f"  Steepening: {dyn['steepening']:.4f}, Twist: {dyn['twist']:.4f}")

    # --- Volatility Targeting ---
    print("\n--- Volatility Targeting ---")
    vt = VolatilityTargeting(target_vol=0.20, vol_lookback=21)
    r_demo = np.random.randn(500) * 0.02
    scaling = vt.scaling_factor(r_demo)
    print(f"  Mean scaling factor: {np.nanmean(scaling):.4f}")
    print(f"  Scaled vol: {np.nanstd(r_demo * scaling) * np.sqrt(252):.4f} "
          f"(target=0.20)")

    # Risk parity
    n_assets = 5
    cov = np.random.randn(n_assets, n_assets)
    cov = cov @ cov.T + np.eye(n_assets) * 0.01
    rp_w = vt.vol_risk_parity(cov, target_vol=0.15)
    port_vol = np.sqrt(rp_w @ cov @ rp_w)
    print(f"  Risk parity weights: {rp_w.round(4)}")
    print(f"  Portfolio vol: {port_vol:.4f} (target=0.15)")

    print("\nDone.")


if __name__ == "__main__":
    _demo()
