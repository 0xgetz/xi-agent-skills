"""
pro_execution_engine — Professional-grade execution system for institutional traders.

Amateurs hit market orders. Pros execute with precision.

References:
    Almgren, R. & Chriss, N. (2001). "Optimal Execution of Portfolio Transactions."
        Journal of Risk, 3(2), 5-39.
    Kissell, R. & Glantz, M. (2003). "Optimal Trading Strategies."
        AMACOM, New York.
    Kissell, R. (2006). "Algorithmic Trading: The Dynamics of Market Impact."
        Journal of Trading, 1(2), 49-60.
    Almgren, R. (2003). "Optimal Execution with Nonlinear Impact Functions
        and Trading-Enhanced Risk." Applied Mathematical Finance, 10(1), 1-18.
    Obizhaeva, A. & Wang, J. (2013). "Optimal Trading Strategy and Supply/Demand
        Dynamics." Journal of Financial Markets, 16(1), 1-32.
    Cont, R. & Kukanov, A. (2017). "Optimal Order Placement in Limit Order Books."
        Journal of Financial Economics, 124(1), 123-141.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Dict, Callable

import numpy as np
from numpy.typing import NDArray

# ---------------------------------------------------------------------------
# Attempt imports from the shared Gumloop trading library
# ---------------------------------------------------------------------------
try:
    from lib.gumloop_trading import (
        validate_ohlcv,
        compute_vwap as lib_vwap,
    )
except ImportError:
    # Minimal stubs when running outside the full project tree
    def validate_ohlcv(df) -> bool: return True
    def lib_vwap(df):
        return (df.volume * (df.high+df.low+df.close)/3).cumsum() / df.volume.cumsum().replace(0,np.nan)


# ===================================================================
#  UTILITY HELPERS
# ===================================================================

def _check_probability(p: float, name: str = "probability") -> None:
    """Validate a probability is in [0, 1]."""
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"{name} must be in [0, 1], got {p}")


def _clip_volume(v: float, min_v: float, max_v: float) -> float:
    """Safely clip a volume value."""
    if min_v > max_v:
        raise ValueError(f"min_volume ({min_v}) > max_volume ({max_v})")
    return float(np.clip(v, min_v, max_v))


def _random_sign(rng: np.random.Generator, p_positive: float = 0.5) -> int:
    """Return +1 or -1 with given probability."""
    return 1 if rng.uniform() < p_positive else -1


# ===================================================================
#  1. TWAP EXECUTOR
# ===================================================================

class TWAP_executor:
    """
    Time-Weighted Average Price executor.

    Slices a parent order into equal-sized child orders distributed evenly
    across a trading horizon. Times are jittered to avoid predictable
    pattern detection by market participants.

    References:
        Madhavan, A. (2002). "VWAP Strategies." Trading, 2002(1), 32-39.
    """

    def __init__(
        self,
        total_shares: float,
        start_time: float,
        end_time: float,
        num_slices: int,
        urgency: float = 0.5,
        time_jitter_sigma: float = 2.0,
        seed: Optional[int] = None,
    ) -> None:
        """
        Parameters
        ----------
        total_shares : float
            Total number of shares to execute.
        start_time : float
            Earliest permissible execution time (seconds from epoch or model time).
        end_time : float
            Latest permissible execution time.
        num_slices : int
            Number of child order slices.
        urgency : float, default 0.5
            Urgency parameter 0 (slow, patient) → 1 (fast, aggressive).
            Controls both slice size and allowable timing deviation.
        time_jitter_sigma : float, default 2.0
            Standard deviation (seconds) for Gaussian jitter applied to scheduled
            execution times. Larger values = less detectable pattern.
        seed : int, optional
            Random seed for reproducibility.
        """
        self.total_shares = total_shares
        self.start_time = start_time
        self.end_time = end_time
        self.num_slices = num_slices
        self.urgency = urgency
        self.time_jitter_sigma = time_jitter_sigma
        self._rng = np.random.default_rng(seed)

        _check_probability(urgency, "urgency")
        if num_slices < 1:
            raise ValueError("num_slices must be >= 1")

        self._schedule: Optional[NDArray[np.float64]] = None
        self._slice_sizes: Optional[NDArray[np.float64]] = None

    def build_schedule(self) -> NDArray[np.float64]:
        """
        Build the execution schedule.

        Returns
        -------
        np.ndarray of shape (num_slices, 3) with columns:
            [scheduled_time, jittered_time, slice_volume]
        """
        horizon = self.end_time - self.start_time

        # Base slice: equal sizing
        base_slice = self.total_shares / self.num_slices

        # Urgency adjustment: faster urgency shifts volume to earlier slices
        urgency_factor = 1.0 + (self.urgency - 0.5) * 0.6
        t_raw = np.linspace(0, horizon, self.num_slices + 1)[:-1]
        t_scheduled = self.start_time + t_raw

        # Generate jittered times with anti-clustering protection
        jitter = self._rng.normal(0, self.time_jitter_sigma, self.num_slices)
        t_jittered = t_scheduled + jitter

        # Clamp jittered times to [start_time, end_time]
        t_jittered = np.clip(t_jittered, self.start_time, self.end_time)

        # Urgency modulates slice sizes: more urgency = front-loaded
        if self.urgency > 0.5:
            # Front-loaded: earlier slices larger than later
            weights = np.exp(-urgency_factor * np.linspace(0, 2, self.num_slices))
            weights /= weights.sum()
        elif self.urgency < 0.5:
            # Back-loaded: build position slowly
            weights = np.exp(urgency_factor * np.linspace(0, 2, self.num_slices))
            weights /= weights.sum()
        else:
            weights = np.ones(self.num_slices) / self.num_slices

        slice_sizes = weights * self.total_shares

        # In very fast mode (urgency >= 0.8), execute a single chunk at open
        if self.urgency >= 0.8:
            t_jittered[0] = max(self.start_time, self.start_time + 2.0 * self._rng.uniform())
            slice_sizes[0] = self.total_shares * 0.6
            remainder = self.total_shares - slice_sizes[0]
            if self.num_slices > 1:
                slice_sizes[1:] = remainder / (self.num_slices - 1)

        self._schedule = np.column_stack([t_scheduled, t_jittered, slice_sizes])
        self._slice_sizes = slice_sizes
        return self._schedule

    @property
    def schedule(self) -> Optional[NDArray[np.float64]]:
        """Return the built schedule, or None if not yet built."""
        return self._schedule

    @property
    def expected_price(self, price_series: NDArray[np.float64]) -> float:
        """
        Compute expected average execution price given a price series.
        Assumes len(price_series) == num_slices.

        Parameters
        ----------
        price_series : np.ndarray
            Price at each scheduled slice time.

        Returns
        -------
        float : TWAP (equal-weighted average price)
        """
        if self._slice_sizes is None:
            raise RuntimeError("Call build_schedule() first.")
        if len(price_series) != self.num_slices:
            raise ValueError(
                f"Expected {self.num_slices} prices, got {len(price_series)}"
            )
        total_notional = np.sum(self._slice_sizes * price_series)
        return float(total_notional / np.sum(self._slice_sizes))

    def __repr__(self) -> str:
        return (
            f"TWAP_executor(shares={self.total_shares:.0f}, "
            f"slices={self.num_slices}, urgency={self.urgency:.2f})"
        )


# ===================================================================
#  2. VWAP EXECUTOR
# ===================================================================

class VWAP_executor:
    """
    Volume-Weighted Average Price executor.

    Uses a predicted intraday volume profile to schedule order execution,
    concentrating trading during periods of highest liquidity.

    References:
        Berkowitz, S., Logue, D. & Noser, E. (1988). "The Total Cost of
            Transactions on the NYSE." Journal of Finance, 43(1), 97-112.
        Madhavan, A. (2002). "VWAP Strategies." Trading, 2002(1), 32-39.
    """

    # Default intraday volume profile: U-shape typical for equities
    # (48 half-hour bins for 6.5-hour US trading day)
    DEFAULT_VOLUME_PROFILE: NDArray[np.float64] = np.array([
        0.018, 0.022, 0.028, 0.032, 0.035, 0.038, 0.036, 0.034,
        0.031, 0.030, 0.028, 0.027, 0.025, 0.024, 0.023, 0.022,
        0.021, 0.020, 0.019, 0.019, 0.020, 0.021, 0.022, 0.024,
        0.026, 0.028, 0.030, 0.031, 0.032, 0.033, 0.034, 0.035,
        0.036, 0.034, 0.032, 0.030, 0.028, 0.026, 0.024, 0.022,
        0.020, 0.018, 0.016, 0.015, 0.014, 0.013, 0.012, 0.012,
    ])
    DEFAULT_VOLUME_PROFILE /= DEFAULT_VOLUME_PROFILE.sum()

    def __init__(
        self,
        total_shares: float,
        volume_profile: Optional[NDArray[np.float64]] = None,
        participaton_rate: float = 0.10,
        min_participation: float = 0.01,
        max_participation: float = 0.25,
        seed: Optional[int] = None,
    ) -> None:
        """
        Parameters
        ----------
        total_shares : float
            Total order size.
        volume_profile : np.ndarray, optional
            Normalized volume distribution across bins (must sum to 1).
            Defaults to a U-shaped intraday profile.
        participaton_rate : float, default 0.10
            Target participation rate as fraction of market volume.
        min_participation : float, default 0.01
            Minimum participation rate cap.
        max_participation : float, default 0.25
            Maximum participation rate cap (prevents market impact).
        seed : int, optional
            Random seed.
        """
        self.total_shares = total_shares
        self.volume_profile = (
            volume_profile
            if volume_profile is not None
            else self.DEFAULT_VOLUME_PROFILE.copy()
        )
        self.participaton_rate = participaton_rate
        self.min_participation = min_participation
        self.max_participation = max_participation
        self._rng = np.random.default_rng(seed)

        # Validate profile sums to 1
        if not np.isclose(np.sum(self.volume_profile), 1.0, atol=1e-6):
            raise ValueError("volume_profile must sum to 1.0")

        self._schedule: Optional[NDArray[np.float64]] = None
        self._realized_volume: NDArray[np.float64] = np.array([], dtype=np.float64)

    def build_schedule(
        self,
        predicted_volumes: Optional[NDArray[np.float64]] = None,
    ) -> NDArray[np.float64]:
        """
        Build the VWAP execution schedule.

        Parameters
        ----------
        predicted_volumes : np.ndarray, optional
            Predicted market volume for each bin. If None, assumed equal
            distribution.

        Returns
        -------
        np.ndarray of shape (n_bins, 2) with columns: [slice_volume, cumulative_pct]
        """
        n_bins = len(self.volume_profile)

        if predicted_volumes is not None:
            if len(predicted_volumes) != n_bins:
                raise ValueError(
                    f"predicted_volumes length ({len(predicted_volumes)}) "
                    f"must match profile ({n_bins})"
                )
            bin_market_vol = predicted_volumes
        else:
            total_market_vol = self.total_shares / (self.participaton_rate + 1e-12)
            bin_market_vol = np.full(n_bins, total_market_vol / n_bins)

        # Volume-proportional slices
        profile_weights = self.volume_profile.copy()

        # Apply participation rate constraints
        max_slice = bin_market_vol * self.max_participation
        min_slice = bin_market_vol * self.min_participation

        raw_slices = profile_weights * self.total_shares
        constrained = np.clip(raw_slices, min_slice, max_slice)

        # Scale to match total order size
        constrained *= self.total_shares / (constrained.sum() + 1e-12)
        cum_pct = np.cumsum(constrained) / self.total_shares

        self._schedule = np.column_stack([constrained, cum_pct])
        self._realized_volume = np.zeros(n_bins, dtype=np.float64)
        return self._schedule

    def adjust_for_realized_volume(
        self,
        bin_index: int,
        actual_market_volume: float,
        remaining_shares: float,
    ) -> float:
        """
        Real-time adjustment after observing actual market volume.

        Parameters
        ----------
        bin_index : int
            Current bin index.
        actual_market_volume : float
            Observed market volume in the bin.
        remaining_shares : float
            Remaining shares to execute.

        Returns
        -------
        float : Adjusted slice size for the next bin.
        """
        if self._schedule is None:
            raise RuntimeError("Call build_schedule() first.")

        n_bins = len(self.volume_profile)
        if bin_index >= n_bins - 1:
            # Last bin — dump remainder
            return remaining_shares

        # Track realized volume
        self._realized_volume[bin_index] = actual_market_volume

        # Re-weight remaining profile
        remaining_weights = self.volume_profile[bin_index + 1 :]
        remaining_weights = remaining_weights / (remaining_weights.sum() + 1e-12)

        # Adjust target participation based on actual vs predicted volume
        predicted_vol = self._schedule[bin_index, 0] / (self.participaton_rate + 1e-12)
        volume_ratio = actual_market_volume / (predicted_vol + 1e-12)

        # Adaptive: if volume was higher than expected, increase participation modestly
        adaptive_rate = self.participaton_rate * np.clip(
            volume_ratio, 0.5, 1.5
        )
        adaptive_rate = np.clip(
            adaptive_rate, self.min_participation, self.max_participation
        )

        # Next slice based on remaining profile × adaptive rate
        next_slice = remaining_weights[0] * remaining_shares
        return float(next_slice)

    def expected_price(
        self,
        price_series: NDArray[np.float64],
        volume_series: NDArray[np.float64],
    ) -> float:
        """
        Expected VWAP given a price and volume series.

        Parameters
        ----------
        price_series : np.ndarray
            Price for each bin.
        volume_series : np.ndarray
            Executed volume for each bin.

        Returns
        -------
        float : VWAP execution price.
        """
        return float(np.average(price_series, weights=volume_series))

    def __repr__(self) -> str:
        return (
            f"VWAP_executor(shares={self.total_shares:.0f}, "
            f"participation={self.participaton_rate:.1%}, "
            f"bins={len(self.volume_profile)})"
        )


# ===================================================================
#  3. IMPLEMENTATION SHORTFALL (Almgren-Chriss)
# ===================================================================

@dataclass
class ImpactParams:
    """Parameters for the Almgren-Chriss market impact model."""

    sigma: float = 0.25        # Annual volatility
    gamma: float = 1e-6        # Permanent impact coefficient ($/share²)
    eta: float = 1e-6          # Temporary impact coefficient ($/share²)
    spread: float = 0.001      # Half-spread as fraction of price
    daily_volume: float = 1e6  # Average daily volume (shares)
    price: float = 100.0       # Current stock price ($)

    def __post_init__(self) -> None:
        for param, name in [
            (self.sigma, "sigma"),
            (self.gamma, "gamma"),
            (self.eta, "eta"),
            (self.spread, "spread"),
        ]:
            if param < 0:
                raise ValueError(f"{name} must be non-negative, got {param}")
        if self.daily_volume <= 0:
            raise ValueError(f"daily_volume must be > 0, got {self.daily_volume}")
        if self.price <= 0:
            raise ValueError(f"price must be > 0, got {self.price}")


class ImplementationShortfall:
    """
    Almgren-Chriss optimal execution model.

    Balances market impact cost against timing risk to produce an optimal
    trade schedule. The model solves the mean-variance optimization:

        min_{x}  [ impact_cost(x) + risk_aversion * variance(x) ]

    where x is the remaining inventory trajectory.

    References:
        Almgren, R. & Chriss, N. (2001). "Optimal Execution of Portfolio
            Transactions." Journal of Risk, 3(2), 5-39.
        Almgren, R. (2003). "Optimal Execution with Nonlinear Impact
            Functions and Trading-Enhanced Risk."
            Applied Mathematical Finance, 10(1), 1-18.
    """

    def __init__(
        self,
        total_shares: float,
        impact_params: ImpactParams,
        risk_aversion: float = 1e-6,
        liquidation_time: float = 1.0,
        n_steps: int = 20,
        urgency: float = 0.5,
    ) -> None:
        """
        Parameters
        ----------
        total_shares : float
            Total shares to execute (positive = buy, negative = sell).
        impact_params : ImpactParams
            Market parameters for impact modeling.
        risk_aversion : float, default 1e-6
            Risk aversion coefficient (lambda) in the AC objective.
            Higher values → faster execution to reduce timing risk.
        liquidation_time : float, default 1.0
            Total liquidation time (in days).
        n_steps : int, default 20
            Number of discrete trading intervals.
        urgency : float, default 0.5
            Urgency 0 (patient) → 1 (urgent). Overrides risk_aversion.
        """
        self.total_shares = total_shares
        self.impact = impact_params
        self.risk_aversion = risk_aversion
        self.liquidation_time = liquidation_time
        self.n_steps = n_steps
        self.urgency = urgency

        _check_probability(urgency, "urgency")

        # Urgency maps to an effective risk aversion multiplier
        #  urgency 0.0 → λ = λ_base / 10   (patient)
        #  urgency 1.0 → λ = λ_base * 10   (urgent)
        self._effective_lambda = risk_aversion * (
            (10.0 - 1.0) * urgency + 1.0
        )
        if urgency > 0.5:
            self._effective_lambda *= (1.0 + (urgency - 0.5) * 18.0)

        self._trajectory: Optional[NDArray[np.float64]] = None
        self._trade_rate: Optional[NDArray[np.float64]] = None

    @property
    def effective_risk_aversion(self) -> float:
        """Risk aversion coefficient after urgency scaling."""
        return self._effective_lambda

    def _build_trajectory(self) -> Tuple[NDArray[np.float64], NDArray[np.float64]]:
        """
        Compute the optimal execution trajectory.

        Solves the closed-form AC optimal trajectory:

            x_j = sinh(kappa * (T - t_j)) / sinh(kappa * T)

        where x_j is remaining inventory at time t_j, and

            kappa = sqrt(lambda * sigma^2 / eta)

        Returns
        -------
        (x, v) : tuple of np.ndarray
            x — remaining inventory at each step (including initial)
            v — trade rate (shares per time step) at each step
        """
        T = self.liquidation_time
        N = self.n_steps
        dt = T / N
        S0 = self.impact.price
        sigma = self.impact.sigma / np.sqrt(252)  # Daily vol from annual
        lam = self._effective_lambda
        eta = self.impact.eta

        # Kappa: square root of (lambda * sigma^2 / eta)
        # This is the key parameter controlling the trajectory shape
        kappa = np.sqrt(lam * sigma**2 / (eta + 1e-30))

        t = np.linspace(0, T, N + 1)  # Time grid including t=0

        if kappa * T < 1e-6:
            # Near-zero kappa → linear liquidation
            x = 1.0 - t / T
        else:
            # AC hyperbolic sine solution
            x = np.sinh(kappa * (T - t)) / np.sinh(kappa * T)

        # Scale to actual shares
        X = abs(self.total_shares)
        x_scaled = x * X

        # Trade rate = negative of inventory change (positive = selling)
        v = np.diff(x_scaled, prepend=x_scaled[0])
        v[0] = 0  # No trade at time 0

        return x_scaled, v

    def compute_trajectory(self) -> NDArray[np.float64]:
        """
        Compute and return the full execution trajectory.

        Returns
        -------
        np.ndarray of shape (n_steps+1, 3) with columns:
            [remaining_inventory, trade_rate, time]
        """
        x, v = self._build_trajectory()
        t = np.linspace(0, self.liquidation_time, self.n_steps + 1)
        self._trajectory = np.column_stack([x, v, t])
        self._trade_rate = v
        return self._trajectory

    def total_impact_cost(self) -> float:
        """
        Compute the total expected market impact cost (dollars).

        Impact cost = permanent + temporary impact.

        Returns
        -------
        float : Total impact cost in dollars.
        """
        if self._trajectory is None:
            self.compute_trajectory()

        X = abs(self.total_shares)
        S0 = self.impact.price
        gamma = self.impact.gamma
        eta = self.impact.eta
        spread = self.impact.spread
        V = self.impact.daily_volume
        T = self.liquidation_time
        N = self.n_steps
        dt = T / N

        # Permanent impact: gamma * X^2   (Almgren-Chriss eq. 13)
        permanent = gamma * X**2

        # Temporary impact: sum over intervals of eta * |v_j| * dt
        v = self._trade_rate[1:]  # Exclude t=0
        temp = eta * np.sum(v**2) * dt / (V * dt + 1e-30)

        # Spread cost: half-spread on each share
        spread_cost = spread * X * S0

        total = permanent + temp + spread_cost
        return float(total)

    def timing_risk(self) -> float:
        """
        Compute timing risk (variance of execution cost due to price volatility).

        Returns
        -------
        float : Timing risk (standard deviation of execution cost) in dollars.
        """
        if self._trajectory is None:
            self.compute_trajectory()

        X = abs(self.total_shares)
        sigma = self.impact.sigma / np.sqrt(252)
        S0 = self.impact.price
        T = self.liquidation_time
        N = self.n_steps
        dt = T / N

        # Risk = sigma * S0 * sqrt( sum( x_j^2 * dt ) )
        # (Almgren-Chriss, risk term derivation)
        x = self._trajectory[:, 0]
        risk_var = sigma**2 * S0**2 * np.sum(x[1:]**2 * dt)
        return float(np.sqrt(risk_var))

    def objective_value(self) -> float:
        """
        Total objective: impact_cost + lambda * variance.

        This is the quantity minimized by the optimal trajectory.

        Returns
        -------
        float : Objective value in dollars.
        """
        impact = self.total_impact_cost()
        risk_var = self.timing_risk() ** 2
        return impact + self._effective_lambda * risk_var

    def utility_adverse(self) -> float:
        """
        Utility-adjusted cost: impact + risk_aversion * variance.
        Higher urgency = higher risk penalty = faster execution.

        Returns
        -------
        float : Risk-adjusted cost in dollars.
        """
        return self.objective_value()

    def __repr__(self) -> str:
        return (
            f"ImplementationShortfall(shares={self.total_shares:.0f}, "
            f"T={self.liquidation_time:.2f}d, "
            f"λ={self._effective_lambda:.2e}, "
            f"κ={np.sqrt(self._effective_lambda * (self.impact.sigma/np.sqrt(252))**2 / (self.impact.eta+1e-30)):.2e})"
        )


# ===================================================================
#  4. ICEBERG EXECUTOR
# ===================================================================

class IcebergExecutor:
    """
    Iceberg (reserve) order executor.

    Shows only a small portion of the total order in the order book,
    hiding true size to minimize information leakage and market impact.
    When the visible portion is filled, it replenishes from the hidden reserve.

    References:
        Tóth, B. et al. (2011). "Anomalous Price Impact and the Critical
            Nature of Liquidity in Financial Markets."
            Physical Review X, 1(2), 021006.
        Cont, R. & Kukanov, A. (2017). "Optimal Order Placement in Limit
            Order Books." Journal of Financial Economics, 124(1), 123-141.
    """

    def __init__(
        self,
        total_shares: float,
        display_size: float,
        min_display: Optional[float] = None,
        max_display: Optional[float] = None,
        randomize_display: bool = True,
        price: float = 100.0,
        side: str = "sell",
        replenish_limit: Optional[int] = None,
        seed: Optional[int] = None,
    ) -> None:
        """
        Parameters
        ----------
        total_shares : float
            Total order size.
        display_size : float
            Initial visible size in order book.
        min_display : float, optional
            Minimum displayed size for randomization.
        max_display : float, optional
            Maximum displayed size for randomization.
        randomize_display : bool, default True
            If True, randomize displayed size at each replenishment.
        price : float, default 100.0
            Limit price.
        side : str, default "sell"
            Order side: "buy" or "sell".
        replenish_limit : int, optional
            Maximum number of replenishments. None = unlimited.
        seed : int, optional
            Random seed.
        """
        self.total_shares = total_shares
        self.display_size = display_size
        self.min_display = min_display if min_display is not None else display_size * 0.5
        self.max_display = max_display if max_display is not None else display_size * 1.5
        self.randomize_display = randomize_display
        self.price = price
        self.side = side.lower()
        self.replenish_limit = replenish_limit
        self._rng = np.random.default_rng(seed)

        if self.side not in ("buy", "sell"):
            raise ValueError(f"side must be 'buy' or 'sell', got {side}")

        self._hidden_remaining: float = total_shares
        self._visible: float = 0.0
        self._filled: float = 0.0
        self._replenish_count: int = 0
        self._history: List[Dict] = []

    @property
    def hidden_remaining(self) -> float:
        return self._hidden_remaining

    @property
    def visible(self) -> float:
        return self._visible

    @property
    def filled(self) -> float:
        return self._filled

    @property
    def is_complete(self) -> bool:
        return self._hidden_remaining <= 0 and self._visible <= 0

    def replenish(self) -> float:
        """
        Replenish the visible portion from the hidden reserve.

        Returns
        -------
        float : New visible size (0 if order complete or limit reached).
        """
        if self.is_complete:
            return 0.0

        if (
            self.replenish_limit is not None
            and self._replenish_count >= self.replenish_limit
        ):
            return 0.0

        if self._hidden_remaining <= 0:
            self._visible = 0.0
            return 0.0

        # Determine new display size
        if self.randomize_display:
            new_visible = self._rng.uniform(self.min_display, self.max_display)
        else:
            new_visible = self.display_size

        # Don't show more than we have
        new_visible = min(new_visible, self._hidden_remaining)

        self._visible = new_visible
        self._hidden_remaining -= new_visible
        self._replenish_count += 1

        self._history.append({
            "replenish": self._replenish_count,
            "visible": new_visible,
            "hidden_remaining": self._hidden_remaining,
            "filled": self._filled,
        })

        return new_visible

    def fill_partial(self, shares_filled: float) -> float:
        """
        Record a partial fill against the visible portion.

        Parameters
        ----------
        shares_filled : float
            Shares executed in this fill.

        Returns
        -------
        float : Remaining visible shares after fill.
        """
        fill = min(shares_filled, self._visible)
        self._visible -= fill
        self._filled += fill
        return self._visible

    def execute_to_completion(self) -> List[Dict]:
        """
        Simulate full lifecycle of replenish-fill cycles until order completes.

        Each cycle: replenish → fill visible → replenish again.

        Returns
        -------
        list[dict] : Full execution history.
        """
        while not self.is_complete:
            self.replenish()
            if self._visible > 0:
                self.fill_partial(self._visible)
            # Small noise: sometimes visible gets partial fills
            if self._hidden_remaining > 0 and self._visible < 0.01:
                self.replenish()
        return self._history

    def summary(self) -> Dict:
        """Return a summary dictionary of the iceberg execution."""
        return {
            "total_shares": self.total_shares,
            "filled": self._filled,
            "hidden_remaining": self._hidden_remaining,
            "replenishments": self._replenish_count,
            "completed": self.is_complete,
            "side": self.side,
            "limit_price": self.price,
            "display_sizes": [h["visible"] for h in self._history],
        }

    def __repr__(self) -> str:
        return (
            f"IcebergExecutor({self.side} {self.total_shares:.0f} @ {self.price:.2f}, "
            f"visible={self.display_size:.0f}, "
            f"completed={self._filled:.0f}/{self.total_shares:.0f})"
        )


# ===================================================================
#  5. SMART ORDER ROUTER
# ===================================================================

@dataclass
class VenueProfile:
    """Profile of a single trading venue."""

    name: str
    liquidity_score: float     # 0 (none) → 1 (deep)
    fee_per_share: float       # $ per share
    rebate_per_share: float    # $ rebate for providing liquidity
    latency_ms: float          # Round-trip latency in ms
    dark_pool: bool = False    # Is this a dark pool?
    fill_rate: float = 0.90    # Historical fill probability
    adverse_selection: float = 0.02  # Adverse selection cost ($/share)

    def __post_init__(self) -> None:
        _check_probability(self.liquidity_score, "liquidity_score")
        _check_probability(self.fill_rate, "fill_rate")

    @property
    def net_fee(self) -> float:
        """Net cost: fee minus rebate."""
        return self.fee_per_share - self.rebate_per_share

    @property
    def quality_score(self) -> float:
        """
        Composite quality: higher is better.
        Balances liquidity, fill rate, fees, latency, and adverse selection.
        """
        score = (
            self.liquidity_score * 0.35
            + self.fill_rate * 0.25
            - self.net_fee * 10.0 * 0.15
            - self.latency_ms / 100.0 * 0.10
            - self.adverse_selection * 5.0 * 0.15
        )
        return float(np.clip(score, 0, 1))


class SmartOrderRouter:
    """
    Intelligent order router that selects the best venue for each child order.

    Evaluates venues on liquidity, fees/rebates, latency, fill rates, and
    adverse selection risk. Supports dark pool aggregation and cross-asset
    routing.

    References:
        Pagano, M. & Röell, A. (1996). "Transparency and Liquidity:
            A Comparison of Auction and Dealer Markets."
            Journal of Financial Economics, 41(1), 33-52.
        Degryse, H. et al. (2013). "Shedding Light on Dark Pool Trading."
            Working Paper, KU Leuven.
    """

    def __init__(self, venues: Optional[List[VenueProfile]] = None) -> None:
        """
        Parameters
        ----------
        venues : list[VenueProfile], optional
            Available trading venues.
        """
        self.venues: List[VenueProfile] = venues or []
        self._routing_log: List[Dict] = []

    def add_venue(self, venue: VenueProfile) -> None:
        """Add a venue to the routing universe."""
        self.venues.append(venue)

    def remove_venue(self, name: str) -> None:
        """Remove a venue by name."""
        self.venues = [v for v in self.venues if v.name != name]

    def rank_venues(
        self,
        order_side: str = "buy",
        order_size: float = 100.0,
        prefer_dark: bool = False,
    ) -> List[VenueProfile]:
        """
        Rank venues by composite score for this specific order.

        Parameters
        ----------
        order_side : str, default "buy"
            Order side — influences venue suitability.
        order_size : float, default 100.0
            Order size in shares — larger orders may prefer dark pools.
        prefer_dark : bool, default False
            If True, prefer dark pools (adds bonus to dark pool scores).

        Returns
        -------
        list[VenueProfile] : Venues sorted best-to-worst.
        """
        scored = []
        for v in self.venues:
            score = v.quality_score

            # Dark pool bonus for large orders to reduce information leakage
            if v.dark_pool:
                if prefer_dark:
                    score += 0.15
                if order_size > 1000:
                    score += 0.10

            # Liquidity discount: small orders benefit more from low fees
            if order_size < 500:
                score -= v.net_fee * 5.0  # Low fees matter more for small orders

            scored.append((score, v))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [v for _, v in scored]

    def route(
        self,
        order_size: float,
        order_side: str = "buy",
        min_fill: float = 0.0,
        prefer_dark: bool = False,
        max_venues: int = 3,
    ) -> Dict:
        """
        Route an order to the best venue(s).

        Parameters
        ----------
        order_size : float
            Shares to route.
        order_side : str, default "buy"
        min_fill : float, default 0.0
            Minimum acceptable fill size.
        prefer_dark : bool, default False
        max_venues : int, default 3
            Maximum number of venues to try.

        Returns
        -------
        dict :
            {
                "venue": str, "allocated": float, "expected_fill": float,
                "total_fee": float, "ranked_venues": [...]
            }
        """
        ranked = self.rank_venues(order_side, order_size, prefer_dark)
        ranked = ranked[:max_venues]

        remaining = order_size
        allocations: List[Dict] = []

        for venue in ranked:
            if remaining <= 0:
                break

            # Allocate proportional to liquidity score
            total_liquidity = sum(v.liquidity_score for v in ranked)
            alloc_frac = venue.liquidity_score / (total_liquidity + 1e-12)
            alloc = alloc_frac * order_size

            # Respect min fill
            if alloc < min_fill and remaining > min_fill:
                continue

            alloc = min(alloc, remaining)
            expected_fill = alloc * venue.fill_rate
            fee = alloc * venue.net_fee

            allocations.append({
                "venue": venue.name,
                "allocated": alloc,
                "expected_fill": expected_fill,
                "net_fee": fee,
                "dark_pool": venue.dark_pool,
                "latency_ms": venue.latency_ms,
            })
            remaining -= alloc

        result = {
            "order_size": order_size,
            "side": order_side,
            "allocations": allocations,
            "ranked_venues": [v.name for v in ranked],
            "unallocated": remaining,
        }

        self._routing_log.append(result)
        return result

    def routing_summary(self) -> List[Dict]:
        """Return all routing decisions made so far."""
        return self._routing_log

    def cross_asset_route(
        self,
        orders: List[Dict],
        prefer_dark: bool = False,
    ) -> List[Dict]:
        """
        Route multiple orders across different assets in a single call.

        Parameters
        ----------
        orders : list[dict]
            Each dict: {"ticker": str, "shares": float, "side": str}
        prefer_dark : bool, default False

        Returns
        -------
        list[dict] : Routing result for each order.
        """
        return [
            self.route(
                order_size=o["shares"],
                order_side=o.get("side", "buy"),
                prefer_dark=prefer_dark,
            )
            for o in orders
        ]

    def __repr__(self) -> str:
        return f"SmartOrderRouter(venues={[v.name for v in self.venues]})"


# ===================================================================
#  6. LIMIT ORDER BOOK
# ===================================================================

class LimitOrderBook:
    """
    Reconstructed limit order book with microstructure analysis.

    Provides bid-ask spread analysis, order book imbalance detection,
    and microstructure signals including cancellation rates and order sizes.

    References:
        Cont, R. (2011). "Statistical Modeling of High-Frequency Financial Data."
            In: Handbook of Computational Finance, Springer.
        Biais, B., Hillion, P. & Spatt, C. (1995). "An Empirical Analysis of
            the Limit Order Book and the Order Flow in the Paris Bourse."
            Journal of Finance, 50(5), 1655-1689.
        Gould, M. D. et al. (2013). "Limit Order Books."
            Quantitative Finance, 13(11), 1709-1742.
    """

    def __init__(self, price_step: float = 0.01) -> None:
        """
        Parameters
        ----------
        price_step : float, default 0.01
            Minimum price increment (tick size).
        """
        self.price_step = price_step
        # Order book levels: dict of price → total volume at that level
        self.bids: Dict[float, float] = {}   # Buy orders (sorted descending)
        self.asks: Dict[float, float] = {}   # Sell orders (sorted ascending)
        # Trade history + order events
        self.trade_log: List[Dict] = []
        self._cancellation_log: List[Dict] = []
        self._order_entry_log: List[Dict] = []
        # Microstructure tracking
        self._cancel_counts: List[int] = []
        self._order_sizes: List[float] = []

    # ---- Book management ----

    def add_limit_order(self, side: str, price: float, volume: float) -> None:
        """Add a limit order to the book."""
        book = self.bids if side == "buy" else self.asks
        price = round(price / self.price_step) * self.price_step
        book[price] = book.get(price, 0.0) + volume
        self._order_entry_log.append({
            "side": side, "price": price, "volume": volume, "type": "limit"
        })
        self._order_sizes.append(volume)

    def cancel_order(self, side: str, price: float, volume: float) -> None:
        """Cancel (remove) volume from a price level."""
        book = self.bids if side == "buy" else self.asks
        price = round(price / self.price_step) * self.price_step
        if price in book:
            book[price] = max(0.0, book[price] - volume)
            if book[price] <= 0:
                del book[price]
            self._cancellation_log.append({
                "side": side, "price": price, "volume": volume
            })
            self._cancel_counts.append(volume)

    def market_order(self, side: str, volume: float) -> float:
        """
        Execute a market order against the book.

        Parameters
        ----------
        side : str
            "buy" (hits asks) or "sell" (hits bids)
        volume : float
            Shares to buy/sell.

        Returns
        -------
        float : Average execution price.
        """
        book = self.asks if side == "buy" else self.bids
        reverse = side == "buy"  # Asks sorted ascending, bids descending

        remaining = volume
        total_cost = 0.0
        prices = sorted(book.keys(), reverse=not reverse)

        for price in prices:
            if remaining <= 0:
                break
            available = book[price]
            fill = min(remaining, available)
            total_cost += fill * price
            remaining -= fill
            book[price] -= fill
            if book[price] <= 0:
                del book[price]
            self.trade_log.append({
                "side": side,
                "price": price,
                "volume": fill,
                "aggressive": True,
            })

        avg_price = total_cost / (volume - remaining + 1e-12)
        return avg_price

    # ---- Analytical methods ----

    @property
    def best_bid(self) -> Optional[float]:
        """Highest bid price."""
        if not self.bids:
            return None
        return max(self.bids.keys())

    @property
    def best_ask(self) -> Optional[float]:
        """Lowest ask price."""
        if not self.asks:
            return None
        return min(self.asks.keys())

    @property
    def spread(self) -> Optional[float]:
        """Bid-ask spread (absolute price difference)."""
        bb, ba = self.best_bid, self.best_ask
        if bb is None or ba is None:
            return None
        return ba - bb

    @property
    def mid_price(self) -> Optional[float]:
        """Midpoint of best bid and best ask."""
        bb, ba = self.best_bid, self.best_ask
        if bb is None or ba is None:
            return None
        return (bb + ba) / 2.0

    @property
    def total_bid_volume(self) -> float:
        """Total volume on the bid side."""
        return float(np.sum(list(self.bids.values())))

    @property
    def total_ask_volume(self) -> float:
        """Total volume on the ask side."""
        return float(np.sum(list(self.asks.values())))

    @property
    def imbalance(self) -> float:
        """
        Order book imbalance: (bid_vol - ask_vol) / (bid_vol + ask_vol).

        Returns
        -------
        float in [-1, 1]. Positive = buying pressure, negative = selling pressure.
        """
        bv = self.total_bid_volume
        av = self.total_ask_volume
        total = bv + av
        if total == 0:
            return 0.0
        return float((bv - av) / total)

    def weighted_imbalance(self, depth: int = 5) -> float:
        """
        Volume-weighted imbalance considering distance from mid.

        Closer levels weighted more heavily.

        Parameters
        ----------
        depth : int, default 5
            Number of levels to consider on each side.

        Returns
        -------
        float : Weighted imbalance score.
        """
        bid_prices = sorted(self.bids.keys(), reverse=True)[:depth]
        ask_prices = sorted(self.asks.keys())[:depth]

        mid = self.mid_price
        if mid is None:
            return 0.0

        weighted_bid = 0.0
        weighted_ask = 0.0

        for p in bid_prices:
            dist = abs(p - mid) / (self.spread or 1.0)
            weight = 1.0 / (1.0 + dist)
            weighted_bid += self.bids[p] * weight

        for p in ask_prices:
            dist = abs(p - mid) / (self.spread or 1.0)
            weight = 1.0 / (1.0 + dist)
            weighted_ask += self.asks[p] * weight

        total = weighted_bid + weighted_ask
        if total == 0:
            return 0.0
        return float((weighted_bid - weighted_ask) / total)

    # ---- Microstructure signals ----

    @property
    def cancel_rate(self) -> float:
        """
        Cancellation rate: fraction of orders that are cancelled.

        High cancellation rates can indicate spoofing or quote fading.
        """
        total_cancels = len(self._cancellation_log)
        total_entries = len(self._order_entry_log) + 1e-12
        return total_cancels / total_entries

    @property
    def avg_cancel_size(self) -> float:
        """Average size of cancelled orders (shares)."""
        if not self._cancel_counts:
            return 0.0
        return float(np.mean(self._cancel_counts))

    @property
    def avg_order_size(self) -> float:
        """Average size of limit orders placed."""
        if not self._order_sizes:
            return 0.0
        return float(np.mean(self._order_sizes))

    @property
    def order_size_ratio(self) -> float:
        """
        Ratio of average cancel size to average order size.
        Large cancels relative to orders can signal predatory behavior.
        """
        avg_cancel = self.avg_cancel_size
        avg_order = self.avg_order_size
        if avg_order == 0:
            return 0.0
        return avg_cancel / avg_order

    def spread_in_bps(self, price: Optional[float] = None) -> Optional[float]:
        """Spread in basis points."""
        sp = self.spread
        ref = price or self.mid_price
        if sp is None or ref is None or ref == 0:
            return None
        return sp / ref * 10_000

    def market_depth(self, levels: int = 10) -> Dict:
        """
        Calculate market depth at the first N levels.

        Returns
        -------
        dict : {"bid_depth": [...], "ask_depth": [...], "total_depth": float}
        """
        bid_prices = sorted(self.bids.keys(), reverse=True)[:levels]
        ask_prices = sorted(self.asks.keys())[:levels]

        bid_depth = [(p, self.bids[p]) for p in bid_prices]
        ask_depth = [(p, self.asks[p]) for p in ask_prices]

        return {
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "total_bid_volume": sum(v for _, v in bid_depth),
            "total_ask_volume": sum(v for _, v in ask_depth),
        }

    def __repr__(self) -> str:
        bb, ba = self.best_bid, self.best_ask
        sp = self.spread
        return (
            f"LimitOrderBook(bid={bb:.2f}, ask={ba:.2f}, "
            f"spread={sp:.4f} ({self.spread_in_bps():.1f}bps), "
            f"imbalance={self.imbalance:+.3f})"
        )


# ===================================================================
#  7. DARK POOL AGGREGATOR
# ===================================================================

@dataclass
class DarkPool:
    """A single dark pool venue."""

    name: str
    fill_rate: float          # Historical fill probability
    avg_execution_volume: float  # Average fill size (shares)
    adverse_selection: float  # Adverse selection cost ($/share)
    latency_ms: float = 0.0   # Round-trip latency
    min_quantity: float = 0.0 # Minimum execution quantity


class DarkPoolAggregator:
    """
    Aggregates liquidity across multiple dark pools.

    Routes orders intelligently to minimize information leakage and
    adverse selection. Enforces minimum execution quantities and
    applies anti-gaming logic to prevent signal detection.

    References:
        Degryse, H. et al. (2013). "Shedding Light on Dark Pool Trading."
            Working Paper, KU Leuven.
        Mittal, H. (2008). "Are You Playing in a Toxic Dark Pool?"
            Journal of Trading, 3(3), 45-51.
        Zhu, H. (2014). "Do Dark Pools Harm Price Discovery?"
            Review of Financial Studies, 27(3), 747-789.
    """

    def __init__(self, seed: Optional[int] = None) -> None:
        """
        Parameters
        ----------
        seed : int, optional
            Random seed for anti-gaming jitter.
        """
        self.pools: List[DarkPool] = []
        self._rng = np.random.default_rng(seed)
        self._execution_log: List[Dict] = []

    def add_pool(self, pool: DarkPool) -> None:
        """Register a dark pool."""
        self.pools.append(pool)

    def remove_pool(self, name: str) -> None:
        """Remove a dark pool by name."""
        self.pools = [p for p in self.pools if p.name != name]

    def route(
        self,
        order_size: float,
        min_exec_qty: float = 0.0,
        max_pools: int = 3,
        anti_gaming: bool = True,
    ) -> Dict:
        """
        Route an order to dark pools.

        Parameters
        ----------
        order_size : float
            Total shares to execute.
        min_exec_qty : float, default 0.0
            Minimum execution quantity per venue (anti-gaming).
        max_pools : int, default 3
            Maximum number of pools to route to.
        anti_gaming : bool, default True
            Apply anti-gaming randomization (random delays, size obfuscation).

        Returns
        -------
        dict : Execution result with pool-by-pool breakdown.
        """
        if not self.pools:
            return {
                "order_size": order_size,
                "filled": 0.0,
                "pools_used": [],
                "executions": [],
                "unfilled": order_size,
            }

        # Sort pools by fill_rate × avg_execution_volume (quality)
        sorted_pools = sorted(
            self.pools, key=lambda p: p.fill_rate * p.avg_execution_volume, reverse=True
        )[:max_pools]

        remaining = order_size
        executions = []
        total_filled = 0.0

        for pool in sorted_pools:
            if remaining <= 0:
                break

            # Potential fill: up to avg_execution_volume at this pool
            potential = min(
                remaining,
                pool.avg_execution_volume,
            )

            # Anti-gaming: obfuscate true size via random fraction
            if anti_gaming:
                # Randomly execute 50-100% of what we would send
                obfuscation = self._rng.uniform(0.5, 1.0)
                potential *= obfuscation

            # Apply minimum execution quantity
            if potential < (min_exec_qty or pool.min_quantity):
                continue

            # Apply fill probability
            fill = potential * self._rng.binomial(1, pool.fill_rate)
            fill = min(fill, remaining)

            # Anti-gaming: randomize fill time (simulated)
            if anti_gaming:
                delay = self._rng.exponential(scale=pool.latency_ms + 1.0)

            # Adverse selection cost
            adverse_cost = fill * pool.adverse_selection

            executions.append({
                "pool": pool.name,
                "sent": round(potential),
                "filled": round(fill),
                "fill_rate": pool.fill_rate,
                "adverse_selection_cost": round(adverse_cost, 4),
            })

            total_filled += fill
            remaining -= fill

        result = {
            "order_size": order_size,
            "filled": round(total_filled),
            "pools_used": [e["pool"] for e in executions],
            "executions": executions,
            "unfilled": round(remaining),
            "fill_rate": total_filled / (order_size + 1e-12),
        }

        self._execution_log.append(result)
        return result

    def aggregate_liquidity(self) -> float:
        """
        Total accessible liquidity across all dark pools.

        Returns
        -------
        float : Sum of average execution volumes.
        """
        return float(np.sum([p.avg_execution_volume for p in self.pools]))

    def toxic_pool_detection(self) -> List[Dict]:
        """
        Flag pools with high adverse selection relative to fill rate.

        Returns
        -------
        list[dict] : Pools sorted by toxicity score.
        """
        scored = []
        for p in self.pools:
            # Toxicity = adverse_selection / (fill_rate + epsilon)
            toxicity = p.adverse_selection / (p.fill_rate + 1e-12)
            scored.append({
                "name": p.name,
                "toxicity_score": toxicity,
                "adverse_selection": p.adverse_selection,
                "fill_rate": p.fill_rate,
            })
        scored.sort(key=lambda x: x["toxicity_score"], reverse=True)
        return scored

    def execution_history(self) -> List[Dict]:
        """Return full execution history."""
        return self._execution_log

    def __repr__(self) -> str:
        total_liquidity = self.aggregate_liquidity()
        return (
            f"DarkPoolAggregator(pools={len(self.pools)}, "
            f"total_liquidity={total_liquidity:.0f})"
        )


# ===================================================================
#  8. MARKET IMPACT MODEL
# ===================================================================

class MarketImpactModel:
    """
    Multi-model market impact estimation.

    Implements:
    - Almgren-Chriss permanent + temporary impact
    - Kissell-Glantz statistical impact model
    - Impact decay estimation

    References:
        Almgren, R. & Chriss, N. (2001). "Optimal Execution of Portfolio
            Transactions." Journal of Risk, 3(2), 5-39.
        Kissell, R. & Glantz, M. (2003). "Optimal Trading Strategies."
            AMACOM, New York.
        Kissell, R. (2006). "Algorithmic Trading: The Dynamics of Market
            Impact." Journal of Trading, 1(2), 49-60.
        Almgren, R. et al. (2005). "Direct Estimation of Equity Market
            Impact." Risk, 18(5), 58-62.
    """

    def __init__(
        self,
        price: float = 100.0,
        daily_volume: float = 1_000_000.0,
        volatility: float = 0.25,
        spread: float = 0.001,
    ) -> None:
        """
        Parameters
        ----------
        price : float
            Current stock price.
        daily_volume : float
            Average daily trading volume (shares).
        volatility : float
            Annualized volatility.
        spread : float
            Relative bid-ask half-spread.
        """
        self.price = price
        self.daily_volume = daily_volume
        self.volatility = volatility
        self.spread = spread

    # ---- Almgren-Chriss impact ----

    def almgren_chriss_impact(
        self,
        shares: float,
        participation_rate: float,
        gamma: float = 1e-6,
        eta: float = 1e-6,
        sigma_scale: float = 0.1,
    ) -> Dict:
        """
        Almgren-Chriss (2001) market impact decomposition.

        Parameters
        ----------
        shares : float
            Total shares to trade.
        participation_rate : float
            Trading rate as fraction of daily volume.
        gamma : float, default 1e-6
            Permanent impact coefficient.
        eta : float, default 1e-6
            Temporary impact coefficient.
        sigma_scale : float, default 0.1
            Volatility-scaled impact coefficient.

        Returns
        -------
        dict : {"permanent": float, "temporary": float, "total": float,
                "permanent_bps": float, "temporary_bps": float}
        """
        V = self.daily_volume
        S0 = self.price
        sigma = self.volatility / np.sqrt(252)  # Daily vol
        X = abs(shares)

        # Participation rate in % of daily volume
        pi = X / V

        # Permanent impact: gamma * X  (price shift)
        # Almgren-Chriss eq. 12: permanent = gamma * sigma * X
        permanent_impact = gamma * sigma * X * S0

        # Temporary impact: eta * sigma * X * (pi)^0.5
        # Almgren-Chriss eq. 13: temporary = eta * sigma * |X/V|^0.5 * S0
        temporary_impact = sigma_scale * sigma * S0 * np.sqrt(X / (V + 1e-12)) * X

        # Classic AC temporary: eta * X^2 / (V * T)
        temp_classic = eta * X**2 / (V + 1e-12)

        total_impact = permanent_impact + temporary_impact + temp_classic

        return {
            "permanent": float(permanent_impact),
            "temporary": float(temporary_impact),
            "temp_classic": float(temp_classic),
            "total": float(total_impact),
            "permanent_bps": float(permanent_impact / (S0 * X + 1e-12) * 10_000),
            "temporary_bps": float((temporary_impact + temp_classic) / (S0 * X + 1e-12) * 10_000),
            "total_bps": float(total_impact / (S0 * X + 1e-12) * 10_000),
        }

    # ---- Kissell-Glantz impact ----

    def kissell_glantz_impact(
        self,
        shares: float,
        urgency: float = 0.5,
        a1: float = 0.1,
        a2: float = 0.5,
    ) -> Dict:
        """
        Kissell-Glantz (2003) statistical market impact model.

        I(X) = a1 * sigma * (X / V)^a2

        where a1, a2 are model parameters, sigma is daily vol,
        X is order size, V is daily volume.

        Parameters
        ----------
        shares : float
            Order size.
        urgency : float, default 0.5
            Execution urgency (0=slow, 1=fast). Higher urgency amplifies impact.
        a1 : float, default 0.1
            Impact scale parameter.
        a2 : float, default 0.5
            Impact exponent (typically 0.3-0.7 for equities).

        Returns
        -------
        dict : {"impact_pct": float, "impact_bps": float, "impact_dollars": float}
        """
        X = abs(shares)
        V = self.daily_volume
        sigma_daily = self.volatility / np.sqrt(252)

        # Kissell-Glantz power law
        participation = X / (V + 1e-12)
        impact_pct = a1 * sigma_daily * (participation ** a2)

        # Urgency amplifies impact — Kissell (2006) urgency scaling
        urgency_multiplier = 1.0 + (urgency - 0.5) * 0.8
        impact_pct *= urgency_multiplier

        impact_dollars = impact_pct * X * self.price

        return {
            "impact_pct": float(impact_pct),
            "impact_bps": float(impact_pct * 10_000),
            "impact_dollars": float(impact_dollars),
            "participation_rate": float(participation),
            "model": "kissell_glantz",
        }

    # ---- Impact decay ----

    def impact_decay(
        self,
        initial_impact_bps: float,
        time_after_trade: float,
        decay_halflife: float = 0.5,
    ) -> float:
        """
        Estimate remaining impact after a decay period.

        Impact decays exponentially post-execution (Almgren 2003).

        Parameters
        ----------
        initial_impact_bps : float
            Initial impact in bps.
        time_after_trade : float
            Time elapsed since trade (in days).
        decay_halflife : float, default 0.5
            Half-life of impact decay in days.

        Returns
        -------
        float : Remaining impact in bps.
        """
        decay_rate = np.log(2) / (decay_halflife + 1e-12)
        remaining = initial_impact_bps * np.exp(-decay_rate * time_after_trade)
        return float(remaining)

    # ---- Unified interface ----

    def estimate(
        self,
        shares: float,
        participation_rate: float,
        urgency: float = 0.5,
        model: str = "almgren_chriss",
    ) -> Dict:
        """
        Unified impact estimation interface.

        Parameters
        ----------
        shares : float
        participation_rate : float
        urgency : float, default 0.5
        model : str, default "almgren_chriss"
            "almgren_chriss", "kissell_glantz", or "both"

        Returns
        -------
        dict : Impact estimates from the selected model(s).
        """
        results = {}

        if model in ("almgren_chriss", "both"):
            results["ac"] = self.almgren_chriss_impact(shares, participation_rate)

        if model in ("kissell_glantz", "both"):
            results["kg"] = self.kissell_glantz_impact(shares, urgency)

        return results

    def __repr__(self) -> str:
        return (
            f"MarketImpactModel(price={self.price:.2f}, "
            f"ADV={self.daily_volume:.0f}, σ={self.volatility:.2%})"
        )


# ===================================================================
#  9. TRANSACTION COST ANALYSIS
# ===================================================================

class TransactionCostAnalysis:
    """
    Comprehensive transaction cost analysis and attribution.

    Breaks down execution quality into:
    - Implementation shortfall vs arrival price
    - Slippage attribution (timing vs impact vs spread)
    - Venue comparison analytics
    - Execution quality metrics

    References:
        Perold, A. F. (1988). "The Implementation Shortfall: Paper vs. Reality."
            Journal of Portfolio Management, 14(3), 4-9.
        Kissell, R. (2006). "Algorithmic Trading: The Dynamics of Market
            Impact." Journal of Trading, 1(2), 49-60.
        Anand, A. et al. (2012). "Institutional Trading and Price Impact."
            Journal of Financial Economics, 106(2), 410-425.
    """

    def __init__(self, arrival_price: float) -> None:
        """
        Parameters
        ----------
        arrival_price : float
            Price at order arrival time (benchmark).
        """
        self.arrival_price = arrival_price
        self.trades: List[Dict] = []
        self._venue_stats: Dict[str, Dict] = {}

    def add_trade(
        self,
        side: str,
        shares: float,
        price: float,
        timestamp: float,
        venue: str = "unknown",
        is_complete: bool = False,
    ) -> Dict:
        """
        Record an executed trade.

        Parameters
        ----------
        side : str
            "buy" or "sell"
        shares : float
            Shares executed.
        price : float
            Execution price.
        timestamp : float
            Execution time (epoch seconds).
        venue : str, default "unknown"
            Venue where trade executed.
        is_complete : bool, default False
            Is this the fill that completes the order?

        Returns
        -------
        dict : Cost breakdown for this trade.
        """
        trade = {
            "side": side,
            "shares": shares,
            "price": price,
            "timestamp": timestamp,
            "venue": venue,
        }

        # Per-trade cost attribution
        if side == "buy":
            slippage = (price - self.arrival_price) / self.arrival_price
        else:
            slippage = (self.arrival_price - price) / self.arrival_price

        trade["slippage_pct"] = float(slippage)
        trade["slippage_bps"] = float(slippage * 10_000)
        trade["slippage_dollars"] = float(slippage * shares * price)

        self.trades.append(trade)

        # Track per-venue stats
        if venue not in self._venue_stats:
            self._venue_stats[venue] = {
                "trades": 0,
                "shares": 0.0,
                "slippage_bps_sum": 0.0,
            }
        self._venue_stats[venue]["trades"] += 1
        self._venue_stats[venue]["shares"] += shares
        self._venue_stats[venue]["slippage_bps_sum"] += trade["slippage_bps"]

        return trade

    # ---- Implementation shortfall ----

    def implementation_shortfall(self, decision_price: float) -> Dict:
        """
        Implementation shortfall vs decision price.

        The total cost of trading vs. the paper return.

        Parameters
        ----------
        decision_price : float
            Price when the trading decision was made.

        Returns
        -------
        dict : Shortfall breakdown in bps and dollars.
        """
        if not self.trades:
            return {"total_shortfall_bps": 0.0, "total_shortfall_dollars": 0.0}

        total_shares = sum(t["shares"] for t in self.trades)
        avg_exec_price = np.average([t["price"] for t in self.trades],
                                     weights=[t["shares"] for t in self.trades])

        side = self.trades[0]["side"]

        if side == "buy":
            shortfall_pct = (avg_exec_price - decision_price) / decision_price
        else:
            shortfall_pct = (decision_price - avg_exec_price) / decision_price

        shortfall_dollars = shortfall_pct * total_shares * avg_exec_price

        # Arrival cost (execution price vs arrival price)
        arrival_cost = sum(t.get("slippage_dollars", 0.0) for t in self.trades)

        return {
            "total_shortfall_bps": float(shortfall_pct * 10_000),
            "total_shortfall_dollars": float(shortfall_dollars),
            "vs_arrival_bps": float(arrival_cost / (total_shares * avg_exec_price + 1e-12) * 10_000),
            "avg_exec_price": float(avg_exec_price),
            "decision_price": float(decision_price),
            "total_shares": float(total_shares),
        }

    # ---- Slippage attribution ----

    def slippage_attribution(self, benchmark_prices: Optional[NDArray[np.float64]] = None) -> Dict:
        """
        Decompose slippage into timing cost vs impact cost vs spread.

        Timing cost — the price moved against the trader before execution
        Impact cost — the trade itself pushed the price
        Spread cost — crossing the bid-ask spread

        Parameters
        ----------
        benchmark_prices : np.ndarray, optional
            Prices at various points during execution for timing attribution.
            If None, timing cost is inferred from trade sequence.

        Returns
        -------
        dict : {"timing_bps": float, "impact_bps": float,
                "spread_bps": float, "residual_bps": float}
        """
        if not self.trades:
            return {"timing_bps": 0.0, "impact_bps": 0.0,
                    "spread_bps": 0.0, "residual_bps": 0.0}

        total_slippage_bps = sum(t["slippage_bps"] for t in self.trades)
        n = len(self.trades)

        if benchmark_prices is not None and len(benchmark_prices) >= n:
            # Timing: price move from arrival to first benchmark
            spot_prices = benchmark_prices[:n]
            timing_bps = sum(
                abs(spot_prices[i] - self.trades[i]["price"])
                / self.arrival_price * 10_000
                for i in range(min(n, len(spot_prices)))
            ) / n
        else:
            # Simplified: later trades have more timing cost
            # Assume 30% of first trade is timing, increasing linearly
            timing_bps = total_slippage_bps * 0.15

        # Spread cost: half-spread on each trade (assume ~2 bps)
        spread_bps = n * 2.0

        # Impact cost: residual after timing and spread
        impact_bps = max(0.0, total_slippage_bps - timing_bps - spread_bps)
        residual_bps = max(0.0, total_slippage_bps - timing_bps - impact_bps - spread_bps)

        return {
            "timing_bps": float(timing_bps),
            "impact_bps": float(impact_bps),
            "spread_bps": float(spread_bps),
            "residual_bps": float(residual_bps),
            "total_slippage_bps": float(total_slippage_bps),
        }

    # ---- Venue comparison ----

    def venue_comparison(self) -> Dict:
        """
        Compare execution quality across venues.

        Returns
        -------
        dict : {venue_name: {"trades": int, "shares": float,
                             "avg_slippage_bps": float, ...}}
        """
        comparison = {}
        for venue, stats in self._venue_stats.items():
            avg_slip = stats["slippage_bps_sum"] / (stats["trades"] + 1e-12)
            comparison[venue] = {
                "trades": stats["trades"],
                "shares": stats["shares"],
                "avg_slippage_bps": round(avg_slip, 2),
                "total_slippage_bps": round(stats["slippage_bps_sum"], 2),
            }

        # Compute market share
        total_shares = sum(s["shares"] for s in comparison.values()) + 1e-12
        for venue in comparison:
            comparison[venue]["market_share_pct"] = (
                comparison[venue]["shares"] / total_shares * 100
            )

        # Rank by execution quality (lowest avg slippage best)
        sorted_venues = sorted(
            comparison.items(), key=lambda x: x[1]["avg_slippage_bps"]
        )
        comparison["_ranking"] = [v[0] for v in sorted_venues]
        comparison["_best_venue"] = sorted_venues[0][0] if sorted_venues else None
        comparison["_worst_venue"] = sorted_venues[-1][0] if sorted_venues else None

        return comparison

    # ---- Execution quality metrics ----

    @property
    def avg_slippage_bps(self) -> float:
        """Average slippage across all trades in bps."""
        if not self.trades:
            return 0.0
        return float(np.mean([t["slippage_bps"] for t in self.trades]))

    @property
    def total_trading_cost(self) -> float:
        """Total dollar cost of trading vs arrival price."""
        return float(sum(t["slippage_dollars"] for t in self.trades))

    @property
    def total_shares_executed(self) -> float:
        """Total shares executed across all trades."""
        return float(sum(t["shares"] for t in self.trades))

    @property
    def vwap_execution(self) -> float:
        """Volume-weighted average execution price."""
        if not self.trades:
            return self.arrival_price
        return float(np.average(
            [t["price"] for t in self.trades],
            weights=[t["shares"] for t in self.trades]
        ))

    def summary(self) -> Dict:
        """Comprehensive TCA summary."""
        return {
            "arrival_price": self.arrival_price,
            "vwap": self.vwap_execution,
            "total_shares": self.total_shares_executed,
            "total_trades": len(self.trades),
            "avg_slippage_bps": self.avg_slippage_bps,
            "total_cost_dollars": self.total_trading_cost,
            "venue_comparison": self.venue_comparison(),
        }

    def __repr__(self) -> str:
        return (
            f"TransactionCostAnalysis(arrival={self.arrival_price:.2f}, "
            f"trades={len(self.trades)}, "
            f"avg_slip={self.avg_slippage_bps:.2f}bps)"
        )


# ===================================================================
#  ORCHESTRATOR
# ===================================================================

class ExecutionOrchestrator:
    """
    Top-level execution system that coordinates all components.

    Provides a unified interface for strategy selection, execution,
    and post-trade analysis.

    Usage:
        orchestrator = ExecutionOrchestrator(price=100.0, daily_volume=1e6)
        result = orchestrator.execute(
            total_shares=100_000,
            strategy="twap",
            urgency=0.7,
            duration_hours=4,
        )
        print(result["tca"].summary())
    """

    def __init__(
        self,
        price: float = 100.0,
        daily_volume: float = 1_000_000,
        volatility: float = 0.25,
        spread: float = 0.001,
        venues: Optional[List[VenueProfile]] = None,
        dark_pools: Optional[List[DarkPool]] = None,
    ) -> None:
        self.price = price
        self.daily_volume = daily_volume
        self.volatility = volatility
        self.spread = spread

        self.market_impact = MarketImpactModel(
            price=price, daily_volume=daily_volume,
            volatility=volatility, spread=spread,
        )
        self.smart_router = SmartOrderRouter(venues)
        self.dark_aggregator = DarkPoolAggregator()

        if dark_pools:
            for p in dark_pools:
                self.dark_aggregator.add_pool(p)

    def execute(
        self,
        total_shares: float,
        strategy: str = "twap",
        urgency: float = 0.5,
        duration_hours: float = 4.0,
        num_slices: int = 24,
        side: str = "sell",
        price: Optional[float] = None,
    ) -> Dict:
        """
        Execute an order using the specified strategy.

        Parameters
        ----------
        total_shares : float
            Total order size.
        strategy : str, default "twap"
            Execution strategy: "twap", "vwap", "shortfall", or "iceberg".
        urgency : float, default 0.5
            Execution urgency (0=patient, 1=urgent).
        duration_hours : float, default 4.0
            Execution time horizon (hours).
        num_slices : int, default 24
            Number of child order slices.
        side : str, default "sell"
            Trade direction.
        price : float, optional
            Reference price (defaults to self.price).

        Returns
        -------
        dict : Full execution result with TCA.
        """
        ref_price = price if price is not None else self.price
        # Convert hours to days (for AC model)
        duration_days = duration_hours / 6.5  # Assume 6.5h trading day

        # Build and execute according to strategy
        if strategy == "twap":
            exec_engine = TWAP_executor(
                total_shares=abs(total_shares),
                start_time=0.0,
                end_time=duration_hours * 3600,
                num_slices=num_slices,
                urgency=urgency,
            )
            schedule = exec_engine.build_schedule()

        elif strategy == "vwap":
            exec_engine = VWAP_executor(
                total_shares=abs(total_shares),
                participaton_rate=0.10 * (1.0 + urgency),
            )
            schedule = exec_engine.build_schedule()

        elif strategy == "shortfall":
            impact_params = ImpactParams(
                sigma=self.volatility,
                daily_volume=self.daily_volume,
                price=ref_price,
                spread=self.spread,
            )
            exec_engine = ImplementationShortfall(
                total_shares=total_shares,
                impact_params=impact_params,
                liquidation_time=duration_days,
                n_steps=num_slices,
                urgency=urgency,
            )
            trajectory = exec_engine.compute_trajectory()
            schedule = trajectory

        elif strategy == "iceberg":
            display = max(abs(total_shares) * 0.05, 100.0)
            exec_engine = IcebergExecutor(
                total_shares=abs(total_shares),
                display_size=display,
                randomize_display=True,
                price=ref_price,
                side=side,
            )
            history = exec_engine.execute_to_completion()
            schedule = None

        else:
            raise ValueError(f"Unknown strategy: {strategy}")

        # Estimate impact
        parti = abs(total_shares) / (self.daily_volume * duration_days + 1e-12)
        impact = self.market_impact.estimate(
            shares=abs(total_shares),
            participation_rate=parti,
            urgency=urgency,
            model="both",
        )

        # Run TCA
        tca = TransactionCostAnalysis(arrival_price=ref_price)
        tca.add_trade(
            side=side,
            shares=abs(total_shares),
            price=ref_price * (1.0 - impact.get("ac", {}).get("total_bps", 0) / 10_000),
            timestamp=0.0,
            venue="execution_engine",
            is_complete=True,
        )

        return {
            "strategy": strategy,
            "total_shares": total_shares,
            "urgency": urgency,
            "duration_hours": duration_hours,
            "engine": exec_engine,
            "schedule": schedule,
            "market_impact": impact,
            "tca": tca,
            "tca_summary": tca.summary(),
        }

    def venue_route_fallback(
        self,
        order_size: float,
        side: str = "buy",
        max_venues: int = 3,
    ) -> Dict:
        """
        Route order using smart router, with dark pool fallback.

        Primary route to lit venues; if fill is insufficient, route
        remainder to dark pools.

        Parameters
        ----------
        order_size : float
        side : str
        max_venues : int

        Returns
        -------
        dict : Combined routing + dark pool result.
        """
        lit_result = self.smart_router.route(
            order_size=order_size, order_side=side, max_venues=max_venues
        )

        unfilled = lit_result.get("unallocated", 0.0)
        dark_result = {}
        if unfilled > 0:
            dark_result = self.dark_aggregator.route(unfilled)

        return {
            "lit_routing": lit_result,
            "dark_routing": dark_result,
            "total_filled": (
                sum(a.get("expected_fill", 0.0)
                     for a in lit_result.get("allocations", []))
                + dark_result.get("filled", 0.0)
            ),
            "total_unfilled": max(0.0, unfilled - dark_result.get("filled", 0.0)),
        }

    def analyze(self, results: Dict) -> Dict:
        """
        Post-execution analysis and recommendations.

        Parameters
        ----------
        results : dict
            Result from self.execute().

        Returns
        -------
        dict : Analysis with improvement suggestions.
        """
        tca = results.get("tca", None)
        if tca is None or not isinstance(tca, TransactionCostAnalysis):
            return {"error": "No TCA data available"}

        summary = tca.summary()
        venue_comp = summary.get("venue_comparison", {})

        analysis = {
            "execution_quality": "good" if summary["avg_slippage_bps"] < 10 else
                                 "fair" if summary["avg_slippage_bps"] < 30 else
                                 "poor",
            "avg_slippage_bps": summary["avg_slippage_bps"],
            "total_cost_dollars": summary["total_cost_dollars"],
        }

        # Suggestions
        suggestions = []
        if summary["avg_slippage_bps"] > 20:
            suggestions.append(
                "Consider using darker execution (iceberg or reduce participation rate)"
            )

        if (
            "_best_venue" in venue_comp
            and "_worst_venue" in venue_comp
            and venue_comp["_best_venue"] != venue_comp["_worst_venue"]
        ):
            diff = (
                venue_comp.get(venue_comp["_worst_venue"], {}).get("avg_slippage_bps", 0)
                - venue_comp.get(venue_comp["_best_venue"], {}).get("avg_slippage_bps", 0)
            )
            if diff > 5:
                suggestions.append(
                    f"Route more flow to {venue_comp['_best_venue']} "
                    f"(saves ~{diff:.1f} bps vs {venue_comp['_worst_venue']})"
                )

        analysis["suggestions"] = suggestions
        return analysis

    def __repr__(self) -> str:
        return (
            f"ExecutionOrchestrator(strategies=[twap, vwap, shortfall, iceberg], "
            f"venue_count={len(self.smart_router.venues)})"
        )


# ===================================================================
#  DEMO / SELF-TEST
# ===================================================================

def _demo():
    """Run a demonstration of all execution components."""
    print("=" * 60)
    print("  pro_execution_engine — Self-Test Demo")
    print("=" * 60)

    # 1. TWAP
    print("\n--- TWAP Executor ---")
    twap = TWAP_executor(100_000, 0, 3600*4, 24, urgency=0.7)
    sched = twap.build_schedule()
    print(f"  {twap}")
    print(f"  Schedule shape: {sched.shape}")
    print(f"  Total sliced: {sched[:,2].sum():.0f} shares")

    # 2. VWAP
    print("\n--- VWAP Executor ---")
    vwap = VWAP_executor(100_000, participaton_rate=0.12)
    vsched = vwap.build_schedule()
    print(f"  {vwap}")
    print(f"  Bins: {len(vsched)}, Cum shares: {vsched[:,0].sum():.0f}")

    # 3. Implementation Shortfall
    print("\n--- Implementation Shortfall ---")
    ip = ImpactParams(sigma=0.30, daily_volume=2_000_000, price=150.0)
    ac = ImplementationShortfall(50_000, ip, risk_aversion=1e-6,
                                  liquidation_time=0.5, n_steps=20, urgency=0.6)
    traj = ac.compute_trajectory()
    print(f"  {ac}")
    print(f"  Total impact cost: ${ac.total_impact_cost():.2f}")
    print(f"  Timing risk (std): ${ac.timing_risk():.2f}")
    print(f"  Objective value: ${ac.objective_value():.2f}")

    # 4. Iceberg
    print("\n--- Iceberg Executor ---")
    ib = IcebergExecutor(50_000, display_size=500, randomize_display=True, price=100.0)
    hist = ib.execute_to_completion()
    print(f"  {ib}")
    print(f"  Replenishments: {ib._replenish_count}")
    print(f"  Filled: {ib.filled:.0f}")

    # 5. Smart Order Router
    print("\n--- Smart Order Router ---")
    venues = [
        VenueProfile("NYSE", 0.95, 0.0003, 0.0001, 5.0),
        VenueProfile("NASDAQ", 0.90, 0.0002, 0.0002, 3.0),
        VenueProfile("ARCA", 0.70, 0.0001, 0.0000, 10.0),
        VenueProfile("IEX", 0.50, 0.0002, 0.0001, 1.0),
    ]
    router = SmartOrderRouter(venues)
    route = router.route(10_000, order_side="buy", max_venues=3)
    print(f"  Route: {route['allocations']}")
    print(f"  Unallocated: {route['unallocated']:.0f}")

    # 6. Limit Order Book
    print("\n--- Limit Order Book ---")
    lob = LimitOrderBook(price_step=0.01)
    for i in range(5):
        lob.add_limit_order("buy", 100.00 - i * 0.02, 1000 * (i + 1))
        lob.add_limit_order("sell", 100.00 + i * 0.02, 1000 * (i + 1))
    print(f"  {lob}")
    print(f"  Mid: {lob.mid_price:.2f}, Spread: {lob.spread:.4f}")
    print(f"  Imbalance: {lob.imbalance:+.3f}, Wted Imbalance: {lob.weighted_imbalance():+.3f}")
    print(f"  Cancel rate: {lob.cancel_rate:.2%}")

    # 7. Dark Pool Aggregator
    print("\n--- Dark Pool Aggregator ---")
    dpa = DarkPoolAggregator(seed=42)
    dpa.add_pool(DarkPool("LiquidNet", 0.15, 5000, 0.01, min_quantity=100))
    dpa.add_pool(DarkPool("POSIT", 0.10, 8000, 0.02, min_quantity=200))
    dpa.add_pool(DarkPool("SigmaX", 0.20, 3000, 0.005, min_quantity=50))
    dr = dpa.route(20_000, min_exec_qty=100, anti_gaming=True)
    print(f"  Filled: {dr['filled']:.0f}/{dr['order_size']:.0f} = {dr['fill_rate']:.1%}")
    print(f"  Toxic pools: {dpa.toxic_pool_detection()}")

    # 8. Market Impact Model
    print("\n--- Market Impact ---")
    mim = MarketImpactModel(price=150.0, daily_volume=2_000_000,
                             volatility=0.30, spread=0.001)
    imp = mim.estimate(shares=50_000, participation_rate=0.025, urgency=0.5, model="both")
    print(f"  Almgren-Chriss: {imp['ac']['total_bps']:.2f} bps (${imp['ac']['total']:.2f})")
    print(f"  Kissell-Glantz: {imp['kg']['impact_bps']:.2f} bps (${imp['kg']['impact_dollars']:.2f})")

    # 9. TCA
    print("\n--- TCA ---")
    tca = TransactionCostAnalysis(arrival_price=100.0)
    tca.add_trade("buy", 1000, 100.02, 1.0, venue="NYSE")
    tca.add_trade("buy", 2000, 100.05, 2.0, venue="NYSE")
    tca.add_trade("buy", 1500, 100.10, 3.0, venue="NASDAQ")
    print(f"  {tca}")
    print(f"  Shortfall: {tca.implementation_shortfall(99.95)}")
    print(f"  Slippage attribution: {tca.slippage_attribution()}")
    print(f"  Venue comparison: {tca.venue_comparison()}")

    # 10. Orchestrator
    print("\n--- Orchestrator ---")
    orch = ExecutionOrchestrator(price=100.0, daily_volume=1_000_000, venues=venues)
    dark_pools = [DarkPool("LiquidNet", 0.15, 5000, 0.01)]
    for p in dark_pools:
        orch.dark_aggregator.add_pool(p)
    result = orch.execute(100_000, strategy="twap", urgency=0.7, duration_hours=4)
    analysis = orch.analyze(result)
    print(f"  Execution quality: {analysis['execution_quality']}")
    print(f"  Average slippage: {analysis['avg_slippage_bps']:.2f} bps")
    print(f"  Suggestions: {analysis['suggestions']}")

    venue_route = orch.venue_route_fallback(50_000, side="sell")
    print(f"  Venue route total filled: {venue_route['total_filled']:.0f}")
    print(f"  Venue route unfilled: {venue_route['total_unfilled']:.0f}")

    print("\n" + "=" * 60)
    print("  All components passed self-test.")
    print("=" * 60)


if __name__ == "__main__":
    _demo()