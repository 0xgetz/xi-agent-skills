
"""
Professional Statistical Arbitrage
====================================
This is what quant hedge funds run. Amateurs can't do this.

Includes:
  - CointegrationEngine    : Engle-Granger, Johansen, half-life, z-score signals
  - PairsTrader            : pair selection, spread normalization, entry/exit, portfolio
  - BasketTrading          : PCA baskets, sector-neutral, factor-mimicking, long-short
  - KalmanFilterPairs      : dynamic hedge ratio, state-space spread, adaptive thresholds
  - CrossAssetArbitrage    : ETF vs basket, futures vs spot, ADR vs underlying
  - StatisticalArbitragePortfolio : multi-pair correlation-aware, neutrality constraints

References:
  Engle & Granger (1987)      - Cointegration
  Johansen (1991)             - Multiple cointegration vectors
  Gatev, Goetzmann & Rouwenhorst (2006) - Pairs trading
  Alexander (2001)            - Orthogonal GARCH / PCA baskets
  Vidyamurthy (2004)          - Pairs Trading (book)
  Avellaneda & Lee (2010)     - Statistical arbitrage in US equities
  Kalman (1960)               - Kalman filter
  Lo & MacKinlay (1997)       - Cross-autocorrelation
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, List, Dict, Callable, Union
from dataclasses import dataclass, field
from scipy import stats
from scipy.optimize import minimize
from sklearn.linear_model import LinearRegression
from sklearn.decomposition import PCA
import warnings

# statsmodels is optional — the module imports cleanly without it, and only the
# cointegration functions that genuinely need it will raise a clear, actionable error.
try:
    from statsmodels.tsa.stattools import adfuller
    from statsmodels.regression.linear_model import OLS
    from statsmodels.tools import add_constant
    from statsmodels.tsa.vector_ar.vecm import coint_johansen
    _HAS_STATSMODELS = True
except ImportError:  # pragma: no cover
    _HAS_STATSMODELS = False

    def _require_statsmodels(*_args, **_kwargs):
        raise ImportError(
            "This function requires 'statsmodels'. Install it with: "
            "pip install statsmodels>=0.14,<0.15"
        )

    # Bind names so references at call time fail with the helpful message above
    adfuller = add_constant = coint_johansen = _require_statsmodels  # type: ignore

    class OLS:  # type: ignore
        def __init__(self, *_a, **_k):
            _require_statsmodels()


def statsmodels_available() -> bool:
    """Return True if statsmodels is installed (cointegration tests available)."""
    return _HAS_STATSMODELS


# ╔══════════════════════════════════════════════════════════════╗
# ║  1. CointegrationEngine                                      ║
# ╚══════════════════════════════════════════════════════════════╝

class CointegrationEngine:
    """
    Cointegration testing and analysis for pairs trading.

    Supports:
      - Engle-Granger two-step test
      - Johansen test (multiple cointegration vectors)
      - Half-life of mean reversion
      - Trading signals from z-score of the spread
    """

    @staticmethod
    def engle_granger(y: np.ndarray, x: np.ndarray,
                      with_constant: bool = True) -> Dict:
        """
        Engle-Granger two-step cointegration test.

        Step 1: Regress y on x to get hedge ratio.
        Step 2: Test residuals for stationarity (ADF test).

        Parameters
        ----------
        y : np.ndarray
            Dependent variable (asset 1 prices).
        x : np.ndarray
            Independent variable (asset 2 prices).
        with_constant : bool
            Include intercept in cointegrating regression.

        Returns
        -------
        dict with keys:
            'hedge_ratio': float or np.ndarray of coefficients
            'intercept': float
            'residuals': np.ndarray
            'adf_stat': float (ADF test statistic)
            'adf_pvalue': float (p-value of ADF test)
            'adf_critical_values': dict of critical values
            'is_cointegrated': bool at 5% level
            'half_life': float (half-life of mean reversion, in periods)
        """
        y, x = np.asarray(y, dtype=float).flatten(), np.asarray(x, dtype=float).flatten()
        T = min(len(y), len(x))
        y, x = y[:T], x[:T]

        # Step 1: Cointegrating regression
        if with_constant:
            X = add_constant(x)
            model = OLS(y, X).fit()
            intercept = float(model.params.iloc[0]) if hasattr(model.params, 'iloc') else float(model.params[0])
            hedge_ratio = float(model.params.iloc[1]) if hasattr(model.params, 'iloc') else float(model.params[1])
            residuals = model.resid
        else:
            model = OLS(y, x).fit()
            intercept = 0.0
            hedge_ratio = float(model.params.iloc[0]) if hasattr(model.params, 'iloc') else float(model.params[0])
            residuals = model.resid

        # Step 2: ADF test on residuals
        adf_result = adfuller(residuals, maxlag=1, autolag='AIC',
                              regression='c')
        adf_stat = float(adf_result[0])
        adf_pvalue = float(adf_result[1])
        critical_values = {k: float(v) for k, v in adf_result[4].items()}
        is_cointegrated = adf_pvalue < 0.05

        # Half-life of mean reversion
        half_life = CointegrationEngine.half_life_of_mean_reversion(residuals)

        return {
            "hedge_ratio": hedge_ratio,
            "intercept": intercept,
            "residuals": residuals,
            "adf_stat": adf_stat,
            "adf_pvalue": adf_pvalue,
            "adf_critical_values": critical_values,
            "is_cointegrated": is_cointegrated,
            "half_life": half_life,
        }

    @staticmethod
    def johansen(data: np.ndarray, det_order: int = 1,
                 k_ar_diff: int = 1) -> Dict:
        """
        Johansen cointegration test (trace and max eigenvalue).

        Tests for multiple cointegrating vectors among a set of series.

        Parameters
        ----------
        data : np.ndarray
            T x N matrix of price series (each column = one series).
        det_order : int
            Deterministic trend order:
             -1 : no trend
              0 : constant
              1 : constant + trend
        k_ar_diff : int
            Number of lags in VAR model (in differences).

        Returns
        -------
        dict with keys:
            'trace_stat': np.ndarray of trace statistics
            'trace_crit': np.ndarray of critical values (95%)
            'max_eigen_stat': np.ndarray of max eigenvalue statistics
            'max_eigen_crit': np.ndarray of critical values (95%)
            'evecs': np.ndarray of cointegrating vectors (columns)
            'evals': np.ndarray of eigenvalues
            'r_trace': int (rank suggested by trace test at 95%)
            'r_max_eigen': int (rank suggested by max eigenvalue at 95%)
        """
        data = np.asarray(data, dtype=float)
        T, N = data.shape
        # statsmodels coint_johansen expects (nobs, neqs) format
        try:
            result = coint_johansen(data, det_order, k_ar_diff)
        except Exception as e:
            # Fallback: reduce lags
            result = coint_johansen(data, det_order, max(1, k_ar_diff - 1))

        # Trace test: H0: rank <= r vs H1: rank > r
        trace_stat = result.lr1  # (N,) array
        trace_crit = result.cvt  # (N, 3) for 90%, 95%, 99%
        # Max eigenvalue: H0: rank = r vs H1: rank = r+1
        max_eigen_stat = result.lr2
        max_eigen_crit = result.cvm

        # Determine rank from 95% critical values (column 1: 95%)
        r_trace = int(np.sum(trace_stat > trace_crit[:, 1]))
        r_max_eigen = int(np.sum(max_eigen_stat > max_eigen_crit[:, 1]))

        return {
            "trace_stat": trace_stat,
            "trace_crit_95": trace_crit[:, 1],
            "max_eigen_stat": max_eigen_stat,
            "max_eigen_crit_95": max_eigen_crit[:, 1],
            "evecs": result.evec,  # N x N matrix
            "evals": result.eig,
            "r_trace": r_trace,
            "r_max_eigen": r_max_eigen,
        }

    @staticmethod
    def half_life_of_mean_reversion(spread: np.ndarray) -> float:
        """
        Compute half-life of mean reversion for a spread series.

        Uses OLS on the AR(1) process:
            spread_{t+1} - spread_t = alpha + beta * spread_t + eps
        Half-life = -log(2) / log(1 + beta)

        If beta >= 0 (no mean reversion), returns np.inf.

        Parameters
        ----------
        spread : np.ndarray
            The spread time series.

        Returns
        -------
        float
            Half-life in periods. np.inf if not mean-reverting.
        """
        spread = np.asarray(spread, dtype=float).flatten()
        # AR(1) in differences: y_t = spread_{t-1}, dy_t = spread_t - spread_{t-1}
        y = spread[:-1]
        dy = np.diff(spread)
        model = OLS(dy, add_constant(y)).fit()
        beta = model.params.iloc[1] if hasattr(model.params, 'iloc') else model.params[1]

        if beta >= 0:
            return np.inf
        hl = -np.log(2) / np.log(1 + beta)
        return float(hl)

    @staticmethod
    def spread_zscore(spread: np.ndarray, window: int = 20) -> np.ndarray:
        """
        Compute z-score of the spread for trading signals.

        z_t = (spread_t - rolling_mean) / rolling_std

        Parameters
        ----------
        spread : np.ndarray
            The spread series.
        window : int
            Rolling window length.

        Returns
        -------
        np.ndarray
            Z-score series (NaN for first n-1 periods).
        """
        spread = pd.Series(np.asarray(spread, dtype=float).flatten())
        mean = spread.rolling(window).mean()
        std = spread.rolling(window).std(ddof=1)
        z = (spread - mean) / np.maximum(std, 1e-8)
        return z.values

    @staticmethod
    def trading_signals(zscore: np.ndarray,
                        entry_z: float = 2.0,
                        exit_z: float = 0.0,
                        stop_z: float = 3.0) -> np.ndarray:
        """
        Generate trading signals from z-score of mean-reverting spread.

        1 = long the spread (buy y, sell x * hedge_ratio)
       -1 = short the spread (sell y, buy x * hedge_ratio)
        0 = no position

        Enter when |z| > entry_z, exit when |z| < exit_z,
        stop-loss when |z| > stop_z.

        Parameters
        ----------
        zscore : np.ndarray
            Z-score series.
        entry_z : float
            Entry threshold (enter at |z| > entry_z).
        exit_z : float
            Exit threshold (exit at |z| < exit_z).
        stop_z : float
            Stop-loss threshold (exit when |z| > stop_z for existing position).

        Returns
        -------
        np.ndarray
            Signals: -1, 0, or 1.
        """
        zscore = np.asarray(zscore, dtype=float).flatten()
        signals = np.zeros(len(zscore), dtype=int)
        position = 0

        for t in range(len(zscore)):
            z = zscore[t]
            if np.isnan(z):
                signals[t] = 0
                continue

            if position == 1:  # long the spread
                if z < exit_z:
                    position = 0  # exit
                elif z > stop_z:
                    position = 0  # stop-loss
                    # Flip to short? Usually close only.
            elif position == -1:  # short the spread
                if z > exit_z:
                    position = 0  # exit
                elif z < -stop_z:
                    position = 0  # stop-loss
            else:  # flat
                if z < -entry_z:
                    position = 1  # long spread (z too low -> mean revert up)
                elif z > entry_z:
                    position = -1  # short spread (z too high -> mean revert down)

            signals[t] = position

        return signals


# ╔══════════════════════════════════════════════════════════════╗
# ║  2. PairsTrader                                               ║
# ╚══════════════════════════════════════════════════════════════╝

@dataclass
class PairInfo:
    """Data for a single trading pair."""
    asset_x: str
    asset_y: str
    hedge_ratio: float = np.nan
    intercept: float = 0.0
    half_life: float = np.inf
    adf_pvalue: float = 1.0
    correlation: float = 0.0
    distance: float = np.inf
    spread: np.ndarray = field(default_factory=lambda: np.array([]))
    zscore: np.ndarray = field(default_factory=lambda: np.array([]))
    is_active: bool = False
    position: int = 0  # 1 long spread, -1 short spread, 0 neutral
    sharpe_estimate: float = 0.0


class PairsTrader:
    """
    Full pairs trading system.

    Pipeline:
      1. Select candidate pairs (distance, correlation, cointegration)
      2. Compute hedge ratio and spread
      3. Normalize spread to z-score
      4. Generate entry/exit signals
      5. Manage a portfolio of the top N pairs
    """

    def __init__(self,
                 entry_z: float = 2.0,
                 exit_z: float = 0.0,
                 stop_z: float = 3.0,
                 zscore_window: int = 20,
                 formation_period: int = 252,
                 min_half_life: int = 5,
                 max_half_life: int = 252,
                 max_adf_pvalue: float = 0.05,
                 min_corr: float = 0.7,
                 top_n: int = 5):
        """
        Parameters
        ----------
        entry_z : float
            Z-score entry threshold.
        exit_z : float
            Z-score exit threshold.
        stop_z : float
            Z-score stop-loss threshold.
        zscore_window : int
            Rolling window for spread z-score.
        formation_period : int
            Lookback period for pair formation.
        min_half_life : int
            Minimum acceptable half-life (faster mean reversion).
        max_half_life : int
            Maximum acceptable half-life (still mean-reverting).
        max_adf_pvalue : float
            Max ADF p-value for cointegration test.
        min_corr : float
            Minimum correlation for pair screening.
        top_n : int
            Number of top pairs to trade simultaneously.
        """
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.stop_z = stop_z
        self.zscore_window = zscore_window
        self.formation_period = formation_period
        self.min_half_life = min_half_life
        self.max_half_life = max_half_life
        self.max_adf_pvalue = max_adf_pvalue
        self.min_corr = min_corr
        self.top_n = top_n
        self.pairs: Dict[Tuple[str, str], PairInfo] = {}
        self.price_data: Optional[pd.DataFrame] = None
        self.pair_rankings_: List[Tuple[float, str, str]] = []

    def select_pairs(self, price_df: pd.DataFrame,
                     method: str = "cointegration") -> List[Tuple[str, str]]:
        """
        Select pairs from a universe of assets.

        Parameters
        ----------
        price_df : pd.DataFrame
            Columns = asset tickers, rows = prices indexed by date.
        method : str
            'cointegration' - test all pairs for cointegration
            'correlation' - high correlation filter then test
            'distance' - minimum squared distance (Gatev et al. 2006)

        Returns
        -------
        list of (asset_x, asset_y) tuples, ranked best to worst.
        """
        self.price_data = price_df
        assets = price_df.columns.tolist()
        T = len(price_df)
        prices = price_df.values.astype(float)

        candidates = []
        log_prices = np.log(np.maximum(prices, 1e-8))

        if method == "distance":
            # Gatev, Goetzmann & Rouwenhorst (2006)
            # Normalize prices to start at 1, then minimize SSD
            normed = prices / prices[:1, :]  # shape (T, N)
            for i in range(len(assets)):
                for j in range(i + 1, len(assets)):
                    ssd = np.sum((normed[:, i] - normed[:, j])**2)
                    candidates.append((ssd, assets[i], assets[j]))
            candidates.sort()
            self.pair_rankings_ = candidates[:self.top_n * 3]

        elif method in ("correlation", "cointegration"):
            # Filter by correlation first
            returns = np.diff(log_prices, axis=0)
            corr_matrix = np.corrcoef(returns.T)
            # Get upper triangle sorted
            for i in range(len(assets)):
                for j in range(i + 1, len(assets)):
                    corr = corr_matrix[i, j]
                    if corr >= self.min_corr:
                        candidates.append((-corr, assets[i], assets[j]))
            candidates.sort()
            self.pair_rankings_ = candidates[:self.top_n * 5]

        # Process candidates (distance-based or cointegration)
        selected_pairs = []
        for score, a1, a2 in self.pair_rankings_:
            if len(selected_pairs) >= self.top_n * 2:
                break
            if method == "cointegration":
                # Run Engle-Granger
                y = prices[:, assets.index(a1)]
                x = prices[:, assets.index(a2)]
                eg = CointegrationEngine.engle_granger(y, x)
                if (eg["is_cointegrated"]
                        and self.min_half_life <= eg["half_life"] <= self.max_half_life):
                    info = PairInfo(
                        asset_x=a2, asset_y=a1,  # y = x*ratio
                        hedge_ratio=eg["hedge_ratio"],
                        intercept=eg["intercept"],
                        half_life=eg["half_life"],
                        adf_pvalue=eg["adf_pvalue"],
                        correlation=corr_matrix[assets.index(a1), assets.index(a2)],
                        spread=eg["residuals"],
                    )
                    self.pairs[(a1, a2)] = info
                    selected_pairs.append((a1, a2))
            elif method in ("correlation", "distance"):
                y = prices[:, assets.index(a1)]
                x = prices[:, assets.index(a2)]
                eg = CointegrationEngine.engle_granger(y, x)
                if eg["is_cointegrated"]:
                    info = PairInfo(
                        asset_x=a2, asset_y=a1,
                        hedge_ratio=eg["hedge_ratio"],
                        intercept=eg["intercept"],
                        half_life=eg["half_life"],
                        adf_pvalue=eg["adf_pvalue"],
                        correlation=corr_matrix[assets.index(a1), assets.index(a2)],
                        spread=eg["residuals"],
                    )
                    self.pairs[(a1, a2)] = info
                    selected_pairs.append((a1, a2))

        # Keep only top N
        if len(selected_pairs) > self.top_n:
            # Sort by half-life (shorter = better)
            selected_pairs.sort(
                key=lambda p: self.pairs[p].half_life
                if np.isfinite(self.pairs[p].half_life) else 1e10)
            selected_pairs = selected_pairs[:self.top_n]
            # Remove pairs not in top N
            for p in list(self.pairs.keys()):
                if p not in selected_pairs:
                    del self.pairs[p]

        # Activate selected pairs
        for p in self.pairs:
            self.pairs[p].is_active = True

        return selected_pairs

    def update_spreads(self, price_df: pd.DataFrame) -> None:
        """
        Update spreads and z-scores for all active pairs with new price data.
        """
        if self.price_data is None:
            self.price_data = price_df
        else:
            self.price_data = pd.concat([self.price_data, price_df])
            self.price_data = self.price_data[~self.price_data.index.duplicated(keep='last')]

        assets = self.price_data.columns.tolist()
        prices = self.price_data.values.astype(float)

        for (a1, a2), info in self.pairs.items():
            if not info.is_active:
                continue
            i1, i2 = assets.index(a1), assets.index(a2)
            y = prices[:, i1]
            x = prices[:, i2]
            spread = y - info.hedge_ratio * x - info.intercept
            info.spread = spread
            info.zscore = CointegrationEngine.spread_zscore(spread, self.zscore_window)

    def generate_signals(self) -> Dict[Tuple[str, str], np.ndarray]:
        """
        Generate trading signals for all pairs.

        Returns
        -------
        dict mapping (asset_x, asset_y) -> array of signals (-1, 0, 1).
        """
        signals = {}
        for pair, info in self.pairs.items():
            if not info.is_active or len(info.zscore) == 0:
                continue
            sig = CointegrationEngine.trading_signals(
                info.zscore, self.entry_z, self.exit_z, self.stop_z)
            info.position = sig[-1] if len(sig) > 0 else 0
            signals[pair] = sig
        return signals

    def rolling_universe(self, price_df: pd.DataFrame,
                         rebalance_every: int = 63,
                         method: str = "cointegration") -> None:
        """
        Dynamically update the pair universe on a rebalancing schedule.

        Re-selects pairs every `rebalance_every` periods from the
        trailing `formation_period` data.
        """
        if len(price_df) < self.formation_period:
            return
        # Roll forward: every rebalance_every periods, re-select
        T = len(price_df)
        rebalance_indices = list(range(self.formation_period, T,
                                        rebalance_every))
        for idx in rebalance_indices:
            window = price_df.iloc[idx - self.formation_period:idx]
            self.select_pairs(window, method=method)

    @staticmethod
    def backtest(pair_signals: Dict[Tuple[str, str], np.ndarray],
                 pair_returns: Dict[Tuple[str, str], np.ndarray]) -> pd.Series:
        """
        Simple backtest of pairs portfolio.

        Parameters
        ----------
        pair_signals : dict
            Mapping of pair -> signal array (-1, 0, 1).
        pair_returns : dict
            Mapping of pair -> spread return array (same length).

        Returns
        -------
        pd.Series of cumulative portfolio returns (equal-weighted).
        """
        if not pair_signals:
            return pd.Series(dtype=float)
        n = len(pair_signals)
        total_returns = np.zeros(len(list(pair_signals.values())[0]))
        for pair in pair_signals:
            signals = pair_signals[pair]
            returns = pair_returns[pair]
            total_returns += signals * returns / n
        return pd.Series(np.cumprod(1 + total_returns), name="port_val")


# ╔══════════════════════════════════════════════════════════════╗
# ║  3. BasketTrading                                             ║
# ╚══════════════════════════════════════════════════════════════╝

class BasketTrading:
    """
    Basket trading strategies: PCA-based, sector-neutral, factor-mimicking.

    PCA decomposition:
      PC1 = market factor
      PCs 2..N = residual alpha sources (idiosyncratic)

    Trade the residuals (stat-arb within the basket).
    """

    def __init__(self, n_components: int = 3):
        """
        Parameters
        ----------
        n_components : int
            Number of principal components to extract.
        """
        self.n_components = n_components
        self.pca_: Optional[PCA] = None
        self.weights_: Optional[np.ndarray] = None
        self.explained_var_ratio_: Optional[np.ndarray] = None
        self.loadings_: Optional[np.ndarray] = None  # (n_assets, n_components)
        self.mean_returns_: Optional[np.ndarray] = None

    def pca_basket(self, returns: np.ndarray) -> np.ndarray:
        """
        PCA decomposition of asset returns.

        Returns residual returns after removing common factors.

        Parameters
        ----------
        returns : np.ndarray
            T x N matrix of asset returns.

        Returns
        -------
        np.ndarray
            T x N matrix of residual returns (orthogonal to PCs).
        """
        returns = np.asarray(returns, dtype=float)
        T, N = returns.shape

        self.mean_returns_ = np.mean(returns, axis=0)
        returns_dm = returns - self.mean_returns_

        self.pca_ = PCA(n_components=min(self.n_components, N, T))
        scores = self.pca_.fit_transform(returns_dm)  # T x K
        self.loadings_ = self.pca_.components_.T  # N x K
        self.explained_var_ratio_ = self.pca_.explained_variance_ratio_
        self.weights_ = self.loadings_  # for portfolio construction

        # Residuals: returns - market factor - other PCs
        # Reconstruct from PCs and subtract
        reconstructed = scores @ self.loadings_.T
        residuals = returns_dm - reconstructed

        return residuals

    def sector_neutral_basket(self, returns: np.ndarray,
                               sector_labels: np.ndarray) -> np.ndarray:
        """
        Construct sector-neutral long-short basket.

        For each sector, go long top X% and short bottom Y% by return.

        Parameters
        ----------
        returns : np.ndarray
            T x N matrix of returns (last row = current).
        sector_labels : np.ndarray
            Length N array of sector identifiers (strings or ints).

        Returns
        -------
        np.ndarray
            Weight vector for the basket (long +, short -).
        """
        returns = np.asarray(returns, dtype=float)
        latest = returns[-1, :] if returns.ndim == 2 else returns
        N = len(latest)
        sectors = np.asarray(sector_labels)
        unique_sectors = np.unique(sectors)

        weights = np.zeros(N)
        for sector in unique_sectors:
            idx = np.where(sectors == sector)[0]
            if len(idx) < 2:
                continue
            sector_rets = latest[idx]
            # Rank within sector
            ranks = np.argsort(sector_rets)
            n_long = max(1, len(idx) // 3)
            n_short = max(1, len(idx) // 3)
            long_idx = idx[ranks[-n_long:]]
            short_idx = idx[ranks[:n_short]]
            weights[long_idx] = 1.0 / len(long_idx) / len(unique_sectors)
            weights[short_idx] = -1.0 / len(short_idx) / len(unique_sectors)

        # Normalize dollar neutrality
        weights = weights - np.mean(weights)
        if np.std(weights) > 0:
            weights = weights / np.std(weights) * 0.1  # 10% vol scaling
        return weights

    def factor_mimicking_portfolio(self, returns: np.ndarray,
                                    factor_exposures: np.ndarray,
                                    target_factor: int = 0) -> np.ndarray:
        """
        Construct a factor-mimicking portfolio.
        Long top x% by factor exposure, short bottom x%.

        Parameters
        ----------
        returns : np.ndarray
            T x N matrix of returns (unused directly; uses last row
            for output).
        factor_exposures : np.ndarray
            N x K matrix of factor loadings for each asset.
        target_factor : int
            Which factor column to target.

        Returns
        -------
        np.ndarray
            Weight vector for the factor-mimicking portfolio.
        """
        exposures = np.asarray(factor_exposures, dtype=float)
        N = exposures.shape[0]
        target_beta = exposures[:, target_factor]

        # Sort by exposure
        order = np.argsort(target_beta)
        n_long = max(1, N // 5)  # top quintile
        n_short = max(1, N // 5)

        weights = np.zeros(N)
        weights[order[-n_long:]] = 1.0 / n_long
        weights[order[:n_short]] = -1.0 / n_short

        # De-mean for dollar neutrality
        weights = weights - np.mean(weights)
        return weights

    def long_short_basket(self, returns: np.ndarray,
                          ranking_scores: np.ndarray,
                          long_pct: float = 0.3,
                          short_pct: float = 0.3) -> np.ndarray:
        """
        Generic long-short basket given ranking scores.

        Parameters
        ----------
        returns : np.ndarray
            T x N matrix (last row used for output scaling).
        ranking_scores : np.ndarray
            Length N array of scores (higher = stronger long signal).
        long_pct : float
            Fraction of assets to go long (top %).
        short_pct : float
            Fraction of assets to go short (bottom %).

        Returns
        -------
        np.ndarray
            Weight vector (sum = 0 for dollar neutrality).
        """
        N = len(ranking_scores)
        order = np.argsort(ranking_scores)
        n_long = max(1, int(N * long_pct))
        n_short = max(1, int(N * short_pct))

        weights = np.zeros(N)
        weights[order[-n_long:]] = 1.0 / n_long
        weights[order[:n_short]] = -1.0 / n_short
        # Dollar neutral
        weights = weights - np.mean(weights)
        return weights


# ╔══════════════════════════════════════════════════════════════╗
# ║  4. KalmanFilterPairs                                         ║
# ╚══════════════════════════════════════════════════════════════╝

class KalmanFilterPairs:
    """
    Kalman filter for pairs trading with time-varying hedge ratio.

    State-space model:
        y_t = alpha_t + beta_t * x_t + eps_t         (observation)
        alpha_{t+1} = alpha_t + xi_t                  (state: intercept)
        beta_{t+1}  = beta_t  + eta_t                 (state: slope)

    The spread (residual) evolves with an adaptive hedge ratio.
    Entry/exit thresholds adapt based on filtered spread volatility.

    References:
      Kalman (1960)
      Vidyamurthy (2004) - Pairs Trading
      Elliott, Van Der Hoek & Malcolm (2005) - Pairs trading via Kalman filter
    """

    def __init__(self,
                 delta: float = 1e-5,
                 ve: float = 1e-3,
                 vw: float = 1e-5,
                 entry_z: float = 2.0,
                 exit_z: float = 0.0,
                 stop_z: float = 3.0,
                 window: int = 20):
        """
        Parameters
        ----------
        delta : float
            State transition covariance scaling.
        ve : float
            Observation noise variance (measurement error).
        vw : float
            State evolution noise variance.
        entry_z, exit_z, stop_z : float
            Z-score thresholds for trading.
        window : int
            Window for adaptive threshold estimation.
        """
        self.delta = delta
        self.ve = ve
        self.vw = vw
        self.entry_z = entry_z
        self.exit_z = exit_z
        self.stop_z = stop_z
        self.window = window

        # Filtered states
        self.alpha_: List[float] = []
        self.beta_: List[float] = []
        self.predictions_: List[float] = []
        self.spread_: List[float] = []
        self.zscore_: List[float] = []

    def fit(self, y: np.ndarray, x: np.ndarray) -> "KalmanFilterPairs":
        """
        Run Kalman filter to estimate time-varying hedge ratio.

        State vector: theta_t = [alpha_t, beta_t]'
        Observation:  y_t = [1, x_t] @ theta_t + eps_t

        Parameters
        ----------
        y : np.ndarray
            Dependent asset price series.
        x : np.ndarray
            Independent asset price series.
        """
        y = np.asarray(y, dtype=float).flatten()
        x = np.asarray(x, dtype=float).flatten()
        T = min(len(y), len(x))
        y, x = y[:T], x[:T]

        # Initial state: OLS on first window
        init_n = min(20, T // 5)
        X0 = np.column_stack([np.ones(init_n), x[:init_n]])
        b_init = np.linalg.lstsq(X0, y[:init_n], rcond=None)[0]

        # State: theta = [alpha, beta]
        theta = b_init.copy()
        # State covariance
        P = np.eye(2) * self.delta
        # Observation matrix: H_t = [1, x_t]
        # Observation noise
        R = self.ve
        # State transition noise
        Q = np.eye(2) * self.vw

        # Storage
        self.alpha_ = [theta[0]]
        self.beta_ = [theta[1]]

        for t in range(init_n, T):
            # Predict
            H = np.array([1.0, x[t]])
            theta_pred = theta
            P_pred = P + Q

            # Update
            innovation = y[t] - H @ theta_pred
            S = H @ P_pred @ H + R
            K = P_pred @ H / S  # Kalman gain

            theta = theta_pred + K * innovation
            P = (np.eye(2) - np.outer(K, H)) @ P_pred

            self.alpha_.append(theta[0])
            self.beta_.append(theta[1])
            self.predictions_.append(H @ theta_pred)
            self.spread_.append(innovation)

        # Pad initial window with NaN
        self.alpha_ = [np.nan] * (init_n - 1) + self.alpha_
        self.beta_ = [np.nan] * (init_n - 1) + self.beta_
        self.predictions_ = [np.nan] * init_n + self.predictions_
        self.spread_ = [np.nan] * init_n + self.spread_

        # Compute z-scores from spread
        self.zscore_ = list(
            CointegrationEngine.spread_zscore(
                np.array(self.spread_), self.window))

        return self

    def signals(self) -> np.ndarray:
        """
        Generate trading signals from the adaptive spread.

        Returns
        -------
        np.ndarray of -1, 0, 1 signals.
        """
        z = np.array(self.zscore_, dtype=float)
        return CointegrationEngine.trading_signals(
            z, self.entry_z, self.exit_z, self.stop_z)

    @property
    def hedge_ratio_series(self) -> pd.Series:
        """Time-varying hedge ratio."""
        return pd.Series(self.beta_, name="hedge_ratio")

    @property
    def spread_series(self) -> pd.Series:
        """Filtered spread (innovation)."""
        return pd.Series(self.spread_, name="spread")

    @property
    def zscore_series(self) -> pd.Series:
        """Spread z-score."""
        return pd.Series(self.zscore_, name="zscore")


# ╔══════════════════════════════════════════════════════════════╗
# ║  5. CrossAssetArbitrage                                       ║
# ╚══════════════════════════════════════════════════════════════╝

class CrossAssetArbitrage:
    """
    Cross-asset arbitrage strategies.

    Covers:
      - ETF vs basket of constituents (creation/redemption arb)
      - Futures vs spot (basis trading)
      - ADR vs underlying stock (dual-listing arbitrage)

    These exploit temporary mispricings between related instruments
    that should converge by the law of one price.
    """

    @staticmethod
    def etf_basket_spread(etf_price: np.ndarray,
                          constituent_prices: np.ndarray,
                          constituent_weights: np.ndarray) -> np.ndarray:
        """
        Compute ETF vs basket-of-constituents spread.

        Spread_t = log(ETF_price_t) - log(weighted_basket_t)

        Parameters
        ----------
        etf_price : np.ndarray
            ETF price series.
        constituent_prices : np.ndarray
            T x N matrix of constituent price series.
        constituent_weights : np.ndarray
            Length N array of constituent weights (sum = 1).

        Returns
        -------
        np.ndarray
            Spread series (log deviations from fair value).
        """
        etf = np.asarray(etf_price, dtype=float).flatten()
        const = np.asarray(constituent_prices, dtype=float)
        w = np.asarray(constituent_weights, dtype=float).flatten()
        w = w / np.sum(w)

        # Weighted basket price
        basket = const @ w
        spread = np.log(etf) - np.log(np.maximum(basket, 1e-8))
        return spread

    @staticmethod
    def futures_basis(futures_price: np.ndarray,
                      spot_price: np.ndarray,
                      time_to_expiry: np.ndarray,
                      rate: float = 0.0,
                      storage_cost: float = 0.0,
                      convenience_yield: float = 0.0) -> np.ndarray:
        """
        Futures basis (deviation from cost-of-carry).

        Fair futures price: F_t = S_t * exp((r + c - y) * tau)
        Basis = log(F_t) - log(F_fair)

        Parameters
        ----------
        futures_price : np.ndarray
            Futures price series.
        spot_price : np.ndarray
            Spot price series.
        time_to_expiry : np.ndarray
            Time to expiry (years), same length.
        rate : float
            Risk-free rate.
        storage_cost : float
            Storage cost rate (for commodities).
        convenience_yield : float
            Convenience yield rate.

        Returns
        -------
        np.ndarray
            Basis series (log deviations from fair value).
        """
        F = np.asarray(futures_price, dtype=float).flatten()
        S = np.asarray(spot_price, dtype=float).flatten()
        tau = np.asarray(time_to_expiry, dtype=float).flatten()
        carry = rate + storage_cost - convenience_yield
        fair_futures = S * np.exp(carry * tau)
        basis = np.log(F) - np.log(np.maximum(fair_futures, 1e-8))
        return basis

    @staticmethod
    def adr_underlying_spread(adr_price: np.ndarray,
                              underlying_price: np.ndarray,
                              fx_rate: np.ndarray,
                              adr_ratio: float = 1.0) -> np.ndarray:
        """
        ADR vs underlying stock mispricing.

        ADR fair = underlying_price * fx_rate * adr_ratio
        Spread = log(ADR_price) - log(ADR_fair)

        Parameters
        ----------
        adr_price : np.ndarray
            ADR price in USD.
        underlying_price : np.ndarray
            Underlying stock price in local currency.
        fx_rate : np.ndarray
            FX rate (USD per local currency).
        adr_ratio : float
            ADR ratio (number of underlying shares per ADR).

        Returns
        -------
        np.ndarray
            Mispricing spread series.
        """
        adr = np.asarray(adr_price, dtype=float).flatten()
        underlying = np.asarray(underlying_price, dtype=float).flatten()
        fx = np.asarray(fx_rate, dtype=float).flatten()
        fair_adr = underlying * fx * adr_ratio
        spread = np.log(adr) - np.log(np.maximum(fair_adr, 1e-8))
        return spread

    @staticmethod
    def mean_reverting_signals(spread: np.ndarray,
                                window: int = 20,
                                entry_z: float = 2.0,
                                exit_z: float = 0.0,
                                stop_z: float = 3.0) -> np.ndarray:
        """
        Generate mean-reversion signals for cross-asset spreads.
        """
        z = CointegrationEngine.spread_zscore(spread, window)
        return CointegrationEngine.trading_signals(z, entry_z, exit_z, stop_z)


# ╔══════════════════════════════════════════════════════════════╗
# ║  6. StatisticalArbitragePortfolio                             ║
# ╚══════════════════════════════════════════════════════════════╝

@dataclass
class PositionLimit:
    """Constraints for a single pair/basket position."""
    max_notional: float = 1_000_000  # max $ exposure
    max_weight: float = 0.20         # max % of portfolio
    min_weight: float = -0.20        # min % of portfolio
    max_correlation_with_others: float = 0.6
    max_beta: float = 1.5
    min_beta: float = -1.5
    sector_exposure_limit: float = 0.30


class StatisticalArbitragePortfolio:
    """
    Multi-strategy statistical arbitrage portfolio manager.

    Manages multiple pairs/baskets simultaneously with:
      - Correlation-aware position limits
      - Sector / country neutrality
      - Dollar neutrality
      - Beta neutrality (market neutral)
      - Factor neutrality (size, value, momentum exposures)

    Each pair is a dollar-neutral long-short position.
    The portfolio ensures aggregate neutrality across constraints.
    """

    def __init__(self,
                 target_vol: float = 0.15,
                 max_leverage: float = 3.0,
                 use_dollar_neutral: bool = True,
                 use_beta_neutral: bool = True,
                 use_sector_neutral: bool = True,
                 use_factor_neutral: bool = False,
                 max_pair_correlation: float = 0.6,
                 position_limit: Optional[PositionLimit] = None):
        """
        Parameters
        ----------
        target_vol : float
            Target annualized portfolio volatility.
        max_leverage : float
            Maximum gross leverage.
        use_dollar_neutral : bool
            Enforce total dollar neutrality.
        use_beta_neutral : bool
            Target market beta = 0.
        use_sector_neutral : bool
            Target sector exposure = 0.
        use_factor_neutral : bool
            Target factor exposure = 0.
        max_pair_correlation : float
            Maximum allowed correlation between any two pairs' returns.
        position_limit : PositionLimit, optional
            Per-pair constraints.
        """
        self.target_vol = target_vol
        self.max_leverage = max_leverage
        self.use_dollar_neutral = use_dollar_neutral
        self.use_beta_neutral = use_beta_neutral
        self.use_sector_neutral = use_sector_neutral
        self.use_factor_neutral = use_factor_neutral
        self.max_pair_correlation = max_pair_correlation
        self.position_limit = position_limit or PositionLimit()

        # Current positions: list of dicts with:
        #   pair_id, asset_long, asset_short, weight, beta, sector, factor_exposures
        self.positions_: List[Dict] = []
        self.correlation_matrix_: Optional[np.ndarray] = None
        self.pair_returns_: Dict[str, np.ndarray] = {}
        self.beta_cache_: Dict[str, float] = {}
        self.sector_cache_: Dict[str, str] = {}
        self.factor_cache_: Dict[str, np.ndarray] = {}

    def add_pair(self, pair_id: str,
                 weight: float,
                 long_asset: str,
                 short_asset: str,
                 beta: float = 0.0,
                 sector: Optional[str] = None,
                 factor_exposures: Optional[np.ndarray] = None) -> bool:
        """
        Add a pair to the portfolio if it passes constraints.

        Parameters
        ----------
        pair_id : str
            Unique identifier for the pair.
        weight : float
            Initial weight (as fraction of equity).
        long_asset, short_asset : str
            Asset identifiers.
        beta : float
            Estimated market beta of the pair spread.
        sector : str, optional
            Sector pair belongs to.
        factor_exposures : np.ndarray, optional
            Factor loadings [size, value, momentum, ...].

        Returns
        -------
        bool
            True if pair was added.
        """
        # Check per-pair constraints
        if abs(weight) > self.position_limit.max_weight:
            return False

        # Check correlation with existing pairs if we have returns
        if len(self.positions_) > 0 and pair_id in self.pair_returns_:
            new_ret = self.pair_returns_[pair_id]
            for pos in self.positions_:
                old_id = pos["pair_id"]
                if old_id in self.pair_returns_:
                    old_ret = self.pair_returns_[old_id]
                    if len(new_ret) > 0 and len(old_ret) > 0:
                        min_len = min(len(new_ret), len(old_ret))
                        corr = np.corrcoef(new_ret[:min_len], old_ret[:min_len])[0, 1]
                        if abs(corr) > self.max_pair_correlation:
                            return False

        position = {
            "pair_id": pair_id,
            "long_asset": long_asset,
            "short_asset": short_asset,
            "weight": weight,
            "beta": beta,
            "sector": sector,
            "factor_exposures": factor_exposures if factor_exposures is not None else np.array([]),
        }
        self.positions_.append(position)
        self.beta_cache_[pair_id] = beta
        if sector:
            self.sector_cache_[pair_id] = sector
        if factor_exposures is not None:
            self.factor_cache_[pair_id] = factor_exposures
        return True

    def set_pair_returns(self, pair_id: str, returns: np.ndarray) -> None:
        """Register return series for a pair (used for correlation)."""
        self.pair_returns_[pair_id] = np.asarray(returns, dtype=float).flatten()

    def optimize_weights(self,
                         cov_matrix: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Optimize pair weights subject to neutrality constraints.

        Minimizes portfolio variance subject to:
          - Dollar neutrality: sum w_i = 0
          - Beta neutrality: sum w_i * beta_i = 0
          - Sector neutrality: sum over each sector = 0
          - Factor neutrality: sum w_i * factor_k = 0 for each factor k
          - Leverage cap: sum |w_i| <= max_leverage

        Parameters
        ----------
        cov_matrix : np.ndarray, optional
            Pair return covariance matrix. If None, uses identity.

        Returns
        -------
        np.ndarray
            Optimized weights for each pair.
        """
        n = len(self.positions_)
        if n == 0:
            return np.array([])

        if cov_matrix is None:
            Sigma = np.eye(n)
        else:
            Sigma = np.asarray(cov_matrix, dtype=float)
            if Sigma.shape != (n, n):
                Sigma = np.eye(n)

        # Objective: minimize w' @ Sigma @ w
        def objective(w):
            return w @ Sigma @ w

        # Constraints
        constraints = []
        # Dollar neutrality
        if self.use_dollar_neutral:
            constraints.append({
                "type": "eq", "fun": lambda w: np.sum(w)
            })

        # Beta neutrality
        if self.use_beta_neutral:
            betas = np.array([p["beta"] for p in self.positions_])
            constraints.append({
                "type": "eq", "fun": lambda w: w @ betas
            })

        # Sector neutrality
        if self.use_sector_neutral:
            sectors = list(set(
                p["sector"] for p in self.positions_ if p["sector"]))
            for sector in sectors:
                mask = np.array([
                    1.0 if p["sector"] == sector else 0.0
                    for p in self.positions_])
                constraints.append({
                    "type": "eq", "fun": lambda w, m=mask: w @ m
                })

        # Factor neutrality
        if self.use_factor_neutral:
            all_series = [
                p["factor_exposures"] for p in self.positions_
                if len(p["factor_exposures"]) > 0]
            if all_series:
                n_factors = min(len(f) for f in all_series)
                for k in range(n_factors):
                    factor_k = np.array([
                        p["factor_exposures"][k] if len(p["factor_exposures"]) > k else 0.0
                        for p in self.positions_])
                    constraints.append({
                        "type": "eq", "fun": lambda w, m=factor_k: w @ m
                    })

        # Leverage constraint
        constraints.append({
            "type": "ineq", "fun": lambda w: self.max_leverage - np.sum(np.abs(w))
        })

        # Per-pair bounds
        bounds = [(self.position_limit.min_weight,
                   self.position_limit.max_weight)] * n

        # Initial guess: equal weights that satisfy dollar neutrality
        x0 = np.zeros(n)
        x0[:n//2] = 1.0 / n
        x0[n//2:] = -1.0 / n

        result = minimize(objective, x0,
                          bounds=bounds,
                          constraints=constraints,
                          method="SLSQP",
                          options={"maxiter": 1000, "ftol": 1e-12})

        if not result.success:
            # Fallback: try trust-constr
            result = minimize(objective, x0,
                              bounds=bounds,
                              constraints=constraints,
                              method="trust-constr",
                              options={"maxiter": 1000, "gtol": 1e-8})

        weights = result.x
        # Scale to target volatility
        port_vol = np.sqrt(weights @ Sigma @ weights)
        if port_vol > 1e-8:
            weights = weights * (self.target_vol / port_vol)

        # Update stored weights
        for i, pos in enumerate(self.positions_):
            pos["weight"] = weights[i]

        return weights

    def compute_correlation_matrix(self) -> np.ndarray:
        """Compute pairwise correlation matrix of all registered pair returns."""
        ids = [p["pair_id"] for p in self.positions_]
        n = len(ids)
        if n == 0:
            self.correlation_matrix_ = np.array([])
            return self.correlation_matrix_

        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                r1 = self.pair_returns_.get(ids[i], np.array([]))
                r2 = self.pair_returns_.get(ids[j], np.array([]))
                if len(r1) > 5 and len(r2) > 5:
                    min_len = min(len(r1), len(r2))
                    c = np.corrcoef(r1[:min_len], r2[:min_len])[0, 1]
                    corr[i, j] = corr[j, i] = c
                else:
                    corr[i, j] = corr[j, i] = 0.0
        self.correlation_matrix_ = corr
        return corr

    def current_exposures(self) -> Dict:
        """
        Compute aggregate portfolio exposures.

        Returns
        -------
        dict with keys:
            'gross_exposure': sum |w_i|
            'net_exposure': sum w_i
            'beta_exposure': sum w_i * beta_i
            'sector_exposures': dict of sector -> exposure
            'key_risk_concentration': Herfindahl index of weights
        """
        if not self.positions_:
            return {}
        weights = np.array([p["weight"] for p in self.positions_])
        betas = np.array([p["beta"] for p in self.positions_])

        gross_exp = np.sum(np.abs(weights))
        net_exp = np.sum(weights)
        beta_exp = weights @ betas

        sector_exp = {}
        for p in self.positions_:
            s = p.get("sector")
            if s:
                sector_exp[s] = sector_exp.get(s, 0.0) + p["weight"]

        # Herfindahl index
        w_norm = weights / (np.sum(np.abs(weights)) + 1e-12)
        herfindahl = np.sum(w_norm**2)

        return {
            "gross_exposure": float(gross_exp),
            "net_exposure": float(net_exp),
            "beta_exposure": float(beta_exp),
            "sector_exposures": sector_exp,
            "herfindahl_index": float(herfindahl),
            "n_pairs": len(self.positions_),
        }

    def risk_budget(self) -> pd.DataFrame:
        """
        Compute marginal risk contributions for each pair.

        Returns
        -------
        pd.DataFrame with columns:
            pair_id, weight, marginal_risk_contribution, percent_risk
        """
        n = len(self.positions_)
        if n == 0:
            return pd.DataFrame()
        Sigma = self.compute_correlation_matrix()
        w = np.array([p["weight"] for p in self.positions_])
        port_var = w @ Sigma @ w
        if port_var <= 0:
            port_var = 1e-8
        port_vol = np.sqrt(port_var)
        mrc = (Sigma @ w) / port_vol
        rc = w * mrc
        rc_pct = rc / (np.sum(rc) + 1e-12) * 100

        df = pd.DataFrame({
            "pair_id": [p["pair_id"] for p in self.positions_],
            "weight": w,
            "marginal_risk_contribution": mrc,
            "risk_contribution": rc,
            "risk_pct": rc_pct,
        })
        return df.sort_values("risk_pct", ascending=False)


# ╔══════════════════════════════════════════════════════════════╗
# ║  Quick Self-Test                                              ║
# ╚══════════════════════════════════════════════════════════════╝

def _demo():
    """Minimal demonstration of the module."""
    np.random.seed(42)
    print("=" * 60)
    print("Statistical Arbitrage Demo")
    print("=" * 60)

    # --- 1. CointegrationEngine ---
    print("\n--- Cointegration ---")
    T = 500
    # Two cointegrated price series
    z = np.cumsum(np.random.randn(T) * 0.01)  # common stochastic trend
    x = 100 + z + np.random.randn(T) * 0.2
    y = 100 + 1.5 * z + np.random.randn(T) * 0.3

    eg = CointegrationEngine.engle_granger(y, x)
    print(f"  Hedge ratio: {eg['hedge_ratio']:.4f} (true=1.5)")
    print(f"  ADF p-value: {eg['adf_pvalue']:.6f}")
    print(f"  Cointegrated: {eg['is_cointegrated']}")
    print(f"  Half-life: {eg['half_life']:.1f} days")

    # Half-life
    hl = CointegrationEngine.half_life_of_mean_reversion(y - 1.5 * x)
    print(f"  Half-life (manual): {hl:.1f}")

    # Z-score signals
    z_scores = CointegrationEngine.spread_zscore(y - 1.5 * x)
    signals = CointegrationEngine.trading_signals(z_scores)
    print(f"  Last 10 signals: {signals[-10:]}")
    print(f"  Trades: {np.sum(np.abs(np.diff(signals)))/2:.0f} round trips")

    # Johansen
    data = np.column_stack([y, x])
    joh = CointegrationEngine.johansen(data, det_order=1, k_ar_diff=1)
    print(f"  Johansen: trace rank={joh['r_trace']}, max-eigen rank={joh['r_max_eigen']}")

    # --- 2. PairsTrader ---
    print("\n--- Pairs Trader ---")
    n_assets = 10
    # Simulate correlated but cointegrated assets
    common = np.cumsum(np.random.randn(T) * 0.02) + 100
    prices = {}
    for i in range(n_assets):
        beta = 0.5 + np.random.random() * 1.5
        noise = np.random.randn(T) * 0.005
        prices[f"ASSET_{i:03d}"] = common * beta + 10 * i + noise * 100
    price_df = pd.DataFrame(prices, index=pd.RangeIndex(T))

    pt = PairsTrader(top_n=3)
    selected = pt.select_pairs(price_df, method="correlation")
    print(f"  Selected {len(selected)} cointegrated pairs:")
    for p in selected:
        info = pt.pairs[p]
        print(f"    {p[0]} / {p[1]}: hl={info.half_life:.1f}, "
              f"corr={info.correlation:.3f}")

    # --- 3. BasketTrading ---
    print("\n--- Basket Trading ---")
    returns = np.random.randn(T, n_assets) * 0.02
    bt = BasketTrading(n_components=3)
    residuals = bt.pca_basket(returns)
    print(f"  Explained variance: {bt.explained_var_ratio_.round(4)}")
    print(f"  Residual returns shape: {residuals.shape}")

    # Sector neutral
    sectors = np.array([f"SECTOR_{i % 3}" for i in range(n_assets)])
    w_sector = bt.sector_neutral_basket(returns, sectors)
    print(f"  Sector-neutral weights: {w_sector.round(4)}")
    print(f"  Net exposure: {w_sector.sum():.6f} (should be ~0)")

    # Long-short
    scores = np.random.randn(n_assets)
    w_ls = bt.long_short_basket(returns, scores)
    print(f"  Long-short weights: {w_ls.round(4)}")

    # --- 4. KalmanFilterPairs ---
    print("\n--- Kalman Filter Pairs ---")
    # Data with time-varying hedge ratio
    kf_T = 400
    true_beta = 0.8 + 0.4 * np.sin(np.arange(kf_T) / 50)  # time-varying
    common_kf = np.cumsum(np.random.randn(kf_T) * 0.02) + 100
    x_kf = common_kf + np.random.randn(kf_T) * 0.1
    y_kf = true_beta * x_kf + np.random.randn(kf_T) * 0.2

    kf = KalmanFilterPairs()
    kf.fit(y_kf, x_kf)
    beta_series = kf.hedge_ratio_series
    sigs = kf.signals()
    print(f"  Beta: last={beta_series.iloc[-1]:.3f}, "
          f"mean={beta_series.mean():.3f}, "
          f"true={true_beta[-1]:.3f}")
    print(f"  Kalman signals: long={np.sum(sigs == 1)}, "
          f"short={np.sum(sigs == -1)}, "
          f"flat={np.sum(sigs == 0)}")

    # --- 5. CrossAssetArbitrage ---
    print("\n--- Cross-Asset Arbitrage ---")
    # ETF-basket spread
    etf_p = np.cumsum(np.random.randn(T) * 0.01) + 100
    const_p = np.column_stack([
        np.cumsum(np.random.randn(T) * 0.01) + 100
        for _ in range(5)])
    w = np.array([0.2] * 5)
    spread_etf = CrossAssetArbitrage.etf_basket_spread(etf_p, const_p, w)
    print(f"  ETF-basket spread: last={spread_etf[-1]:.6f}, "
          f"std={np.nanstd(spread_etf):.6f}")

    # Futures basis
    F = np.cumsum(np.random.randn(T) * 0.01) + 100
    S = 100 + np.cumsum(np.random.randn(T) * 0.01)
    tau = np.ones(T) * 0.25
    basis = CrossAssetArbitrage.futures_basis(F, S, tau, rate=0.05)
    print(f"  Futures basis: last={basis[-1]:.6f}, std={np.nanstd(basis):.4f}")

    # --- 6. StatisticalArbitragePortfolio ---
    print("\n--- Stat-Arb Portfolio ---")
    sap = StatisticalArbitragePortfolio(
        target_vol=0.15,
        use_dollar_neutral=True,
        use_beta_neutral=True,
        use_sector_neutral=True,
        max_pair_correlation=0.5)

    # Add some pairs
    for i in range(5):
        beta_val = np.random.uniform(-0.3, 0.3)
        sector = np.random.choice(["TECH", "FIN", "ENERGY"])
        sap.add_pair(
            pair_id=f"PAIR_{i:02d}",
            weight=np.random.uniform(-0.1, 0.1),
            long_asset=f"A{i*2}",
            short_asset=f"A{i*2+1}",
            beta=beta_val,
            sector=sector,
            factor_exposures=np.random.randn(3) * 0.1,
        )

    # Set dummy returns
    for p in sap.positions_:
        sap.set_pair_returns(p["pair_id"], np.random.randn(T) * 0.005)

    # Optimize
    weights = sap.optimize_weights()
    exposures = sap.current_exposures()
    print(f"  Net exposure: {exposures['net_exposure']:.6f}")
    print(f"  Gross exposure: {exposures['gross_exposure']:.4f}")
    print(f"  Beta exposure: {exposures['beta_exposure']:.6f}")
    print(f"  Sector exposures: {exposures['sector_exposures']}")
    risk_df = sap.risk_budget()
    print("  Risk budget (top 3):")
    print(f"    {risk_df.head(3).to_string().replace(chr(10), chr(10) + '    ')}")

    print("\nDone.")


if __name__ == "__main__":
    _demo()
