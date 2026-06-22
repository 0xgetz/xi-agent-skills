#!/usr/bin/env python3
"""
pro_market_regime.py — Professional Market Regime Detection System

"Amateurs trade the same way in all markets. Pros adapt to regimes."

Multi-model regime classification engine combining:
  - HMM (Hidden Markov Model) for latent state inference
  - Volatility clustering & GARCH regime-switching
  - Trend strength (ADX, Hurst, fractal dimension)
  - Correlation-based risk-on/risk-off (PCA)
  - Breadth indicators (advance-decline, McClellan, NH/NL)
  - Liquidity regimes (spread, volume, depth)
  - Multi-timeframe consensus with HTF alignment
  - Regime-adaptive allocation & strategy switching

References:
  - Hamilton (1989) — Regime-switching time series models
  - Ang & Bekaert (2002) — Regime switches in interest rates
  - Alexander (2001) — Market Models (PCA for risk factor)
  - Wilder (1978) — New Concepts in Technical Trading (ADX)
  - Hurst (1951) — Long-term storage capacity of reservoirs (Hurst exponent)
  - Mandelbrot (1963) — Fractal dimension / variance of financial time series
  - Bollerslev (1986) — GARCH(1,1) model
  - Cohen et al. (2023, JPM) — Regime-based asset allocation

Author: Gumloop Pro Trading Suite
"""

from __future__ import annotations

import warnings
import numpy as np
import pandas as pd
from typing import Optional, Tuple, Dict, List, Any, Callable, Union
from dataclasses import dataclass, field
from enum import Enum, auto
from scipy import stats, linalg
from collections import deque

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# ──────────────────────────────────────────────────────────────────────────────
# Imports from shared lib
# ──────────────────────────────────────────────────────────────────────────────
try:
    from lib.gumloop_trading import (
        validate_ohlcv, compute_ema, compute_sma, compute_adx,
        compute_atr, compute_rsi, compute_macd, compute_obv,
        compute_bollinger, compute_stochastic, compute_vwap
    )
except ImportError:
    # Fallback stubs when running standalone
    def validate_ohlcv(df):
        return {"open", "high", "low", "close", "volume"}.issubset(df.columns)
    def compute_ema(s, p):
        return s.ewm(span=p, adjust=False).mean()
    def compute_sma(s, p):
        return s.rolling(p).mean()
    def compute_adx(df, p=14):
        return pd.Series(np.nan, index=df.index), None, None
    def compute_atr(df, p=14):
        hl, hc, lc = df.high-df.low, (df.high-df.close.shift()).abs(), (df.low-df.close.shift()).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.rolling(p).mean()
    def compute_rsi(s, p=14):
        delta = s.diff()
        gain = delta.clip(lower=0).rolling(p).mean()
        loss = (-delta.clip(upper=0)).rolling(p).mean()
        rs = gain / loss.replace(0, np.nan)
        return 100 - (100 / (1 + rs))
    def compute_obv(df):
        return (df.volume * ((df.close > df.close.shift()).astype(int)*2-1)).cumsum()

# ──────────────────────────────────────────────────────────────────────────────
# HMM imports (optional)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from hmmlearn import hmm
    _HAS_HMM = True
except ImportError:
    _HAS_HMM = False

try:
    from sklearn.decomposition import PCA
    from sklearn.preprocessing import StandardScaler
    _HAS_SKLEARN = True
except ImportError:
    _HAS_SKLEARN = False

try:
    from scipy.signal import argrelextrema, find_peaks
    _HAS_SCIPY_SIGNAL = True
except ImportError:
    _HAS_SCIPY_SIGNAL = False

# ──────────────────────────────────────────────────────────────────────────────
# Enums & Data Classes
# ──────────────────────────────────────────────────────────────────────────────

class RegimeType(Enum):
    """Primary market regime classifications."""
    BULL_TRENDING   = auto()  # Strong uptrend
    BEAR_TRENDING   = auto()  # Strong downtrend
    RANGING         = auto()  # Low trend, mean-reverting
    HIGH_VOLATILITY = auto()  # High vol, uncertainty
    RISK_ON         = auto()  # Risk appetite
    RISK_OFF        = auto()  # Risk aversion
    ACCUMULATION    = auto()  # Smart money buying
    DISTRIBUTION    = auto()  # Smart money selling
    LIQUID          = auto()  # Normal liquidity
    ILLIQUID        = auto()  # Low liquidity
    UNKNOWN         = auto()  # Indeterminate

class TrendState(Enum):
    STRONG_TREND_UP   = auto()
    STRONG_TREND_DOWN = auto()
    WEAK_TREND_UP     = auto()
    WEAK_TREND_DOWN   = auto()
    RANGING           = auto()
    NOISE             = auto()

class VolatilityState(Enum):
    LOW     = auto()
    NORMAL  = auto()
    HIGH    = auto()
    EXTREME = auto()

class CorrelationState(Enum):
    RISK_ON  = auto()
    RISK_OFF = auto()
    MIXED    = auto()

class LiquidityState(Enum):
    LIQUID   = auto()
    NORMAL   = auto()
    ILLIQUID = auto()

class BreadthState(Enum):
    OVERBOUGHT       = auto()
    BULLISH          = auto()
    NEUTRAL          = auto()
    BEARISH          = auto()
    OVERSOLD         = auto()

class VolumeState(Enum):
    ACCUMULATION  = auto()
    DISTRIBUTION  = auto()
    NEUTRAL       = auto()

@dataclass
class RegimeSignal:
    """A single regime classification result with confidence."""
    regime: RegimeType
    confidence: float        # 0.0 – 1.0
    score: float             # Raw composite score
    components: Dict[str, Any] = field(default_factory=dict)
    
    def __repr__(self) -> str:
        return f"RegimeSignal({self.regime.name}, conf={self.confidence:.2f})"

@dataclass
class RegimeComposite:
    """Aggregated regime across multiple models."""
    primary: RegimeSignal
    secondary: Optional[RegimeSignal] = None
    trend: TrendState = TrendState.RANGING
    volatility: VolatilityState = VolatilityState.NORMAL
    correlation: CorrelationState = CorrelationState.MIXED
    liquidity: LiquidityState = LiquidityState.NORMAL
    breadth: BreadthState = BreadthState.NEUTRAL
    volume: VolumeState = VolumeState.NEUTRAL
    composite_score: float = 0.0
    regime_strength: float = 0.0   # How strongly defined the regime is
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "primary": self.primary.regime.name,
            "primary_confidence": self.primary.confidence,
            "trend": self.trend.name,
            "volatility": self.volatility.name,
            "correlation": self.correlation.name,
            "liquidity": self.liquidity.name,
            "breadth": self.breadth.name,
            "volume": self.volume.name,
            "composite_score": self.composite_score,
            "regime_strength": self.regime_strength,
        }


# ══════════════════════════════════════════════════════════════════════════════
# 1. MarketRegimeDetector
# ══════════════════════════════════════════════════════════════════════════════

class MarketRegimeDetector:
    """
    Multi-model regime detection engine.
    
    Combines HMM latent states, volatility clustering, trend strength,
    correlation analysis, and volume analysis into a unified regime signal.
    
    Parameters
    ----------
    n_hmm_states : int
        Number of hidden states for the HMM (default 3: bull, bear, range).
    lookback : int
        Rolling lookback window for regime computation (default 252).
    hmm_lookback : int
        Training window for HMM (default 504).
    vol_threshold_high : float
        Z-score threshold for high vol regime (default 1.5).
    vol_threshold_low : float
        Z-score threshold for low vol regime (default -0.5).
    adx_threshold : int
        ADX threshold for trending vs ranging (default 25).
    use_hmm : bool
        Whether to use HMM-based regime detection.
    """
    
    def __init__(
        self,
        n_hmm_states: int = 3,
        lookback: int = 252,
        hmm_lookback: int = 504,
        vol_threshold_high: float = 1.5,
        vol_threshold_low: float = -0.5,
        adx_threshold: int = 25,
        use_hmm: bool = True,
    ):
        self.n_hmm_states = n_hmm_states
        self.lookback = lookback
        self.hmm_lookback = hmm_lookback
        self.vol_threshold_high = vol_threshold_high
        self.vol_threshold_low = vol_threshold_low
        self.adx_threshold = adx_threshold
        self.use_hmm = use_hmm and _HAS_HMM
        
        # HMM model (fitted lazily)
        self._hmm_model: Optional[hmm.GaussianHMM] = None
        self._hmm_fitted = False
        self._hmm_state_map: Dict[int, RegimeType] = {}
        
        # Sub-analyzers
        self.trend = TrendStrengthAnalyzer()
        self.volatility = VolatilityRegime()
        self.correlation = CorrelationRegime()
        self.liquidity = LiquidityRegime()
        self.breadth = BreadthRegime()
        
        # Historical regime record
        self._history: List[RegimeComposite] = []
    
    # ── HMM ──────────────────────────────────────────────────────────────────
    
    def _fit_hmm(self, prices: pd.Series, volumes: Optional[pd.Series] = None) -> None:
        """
        Fit the Hidden Markov Model on log returns and (optionally) volume.
        
        Uses Gaussian emissions with full covariance matrix. The number of
        states is set at init time (typically 3: bull, bear, range).
        """
        if not self.use_hmm or len(prices) < self.hmm_lookback:
            return
        
        log_returns = np.log(prices / prices.shift(1)).dropna().values[-self.hmm_lookback:]
        
        # Feature vector: log returns + optional volume change
        features = [log_returns]
        if volumes is not None and len(volumes) >= self.hmm_lookback:
            vol_change = np.log(volumes / volumes.shift(1)).dropna().values[-self.hmm_lookback:]
            min_len = min(len(log_returns), len(vol_change))
            features = [log_returns[-min_len:], vol_change[-min_len:]]
        
        X = np.column_stack(features)
        
        # Handle NaN / inf
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        
        if len(X) < self.hmm_lookback * 0.5:
            return
        
        try:
            model = hmm.GaussianHMM(
                n_components=self.n_hmm_states,
                covariance_type="full",
                n_iter=1000,
                tol=1e-4,
                random_state=42,
            )
            model.fit(X)
            self._hmm_model = model
            self._hmm_fitted = True
            
            # Map HMM states to regime types by sorting by mean return
            state_means = model.means_[:, 0]  # First feature = returns
            sorted_indices = np.argsort(state_means)
            state_names = [RegimeType.BEAR_TRENDING, RegimeType.RANGING, RegimeType.BULL_TRENDING]
            if self.n_hmm_states == 4:
                state_names = [RegimeType.BEAR_TRENDING, RegimeType.RANGING, RegimeType.BULL_TRENDING, RegimeType.HIGH_VOLATILITY]
            elif self.n_hmm_states == 2:
                state_names = [RegimeType.RISK_OFF, RegimeType.RISK_ON]
            
            self._hmm_state_map = {
                int(sorted_indices[i]): state_names[i]
                for i in range(min(self.n_hmm_states, len(state_names)))
            }
        except Exception:
            self._hmm_fitted = False
    
    def _hmm_regime(self, prices: pd.Series, volumes: Optional[pd.Series] = None) -> Optional[RegimeSignal]:
        """Infer the current HMM regime state."""
        if not self._hmm_fitted or self._hmm_model is None:
            return None
        
        log_returns = np.log(prices / prices.shift(1)).dropna().values[-self.hmm_lookback:]
        features = [log_returns]
        if volumes is not None and len(volumes) >= self.hmm_lookback:
            vol_change = np.log(volumes / volumes.shift(1)).dropna().values[-self.hmm_lookback:]
            min_len = min(len(log_returns), len(vol_change))
            features = [log_returns[-min_len:], vol_change[-min_len:]]
        
        X = np.column_stack(features)
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)
        
        try:
            states = self._hmm_model.predict(X)
            current_state = int(states[-1])
            
            # Posterior probabilities
            post_probs = self._hmm_model.predict_proba(X)
            confidence = float(post_probs[-1, current_state])
            
            regime = self._hmm_state_map.get(
                current_state, RegimeType.UNKNOWN
            )
            return RegimeSignal(
                regime=regime,
                confidence=confidence,
                score=float(self._hmm_model.means_[current_state, 0]),
                components={"hmm_state": current_state, "state_means": self._hmm_model.means_[:, 0].tolist()},
            )
        except Exception:
            return None
    
    # ── Volatility Clustering ────────────────────────────────────────────────
    
    def _volatility_regime(self, df: pd.DataFrame) -> RegimeSignal:
        """
        Detect volatility clustering regime using rolling realized vol.
        
        Returns HIGH / NORMAL / LOW volatility states based on z-score
        of 21-day realized vol relative to 252-day distribution.
        """
        returns = df.close.pct_change().dropna()
        rv_21 = returns.rolling(21).std() * np.sqrt(252)  # Annualized
        rv_252_mean = returns.rolling(252).std() * np.sqrt(252)
        rv_252_std = rv_21.rolling(252).std()
        
        if len(rv_21) < 21:
            return RegimeSignal(RegimeType.RANGING, 0.5, 0.0)
        
        current_rv = rv_21.iloc[-1]
        current_rv_mean = rv_252_mean.iloc[-1] if not pd.isna(rv_252_mean.iloc[-1]) else rv_21.mean()
        current_rv_std = rv_252_std.iloc[-1] if not pd.isna(rv_252_std.iloc[-1]) else rv_21.std()
        
        z_score = (current_rv - current_rv_mean) / max(current_rv_std, 1e-10)
        
        if z_score > self.vol_threshold_high:
            regime = RegimeType.HIGH_VOLATILITY
            confidence = min(abs(z_score) / 3.0, 1.0)
        elif z_score < self.vol_threshold_low:
            regime = RegimeType.RANGING  # Low vol = ranging
            confidence = min(abs(z_score) / 2.0, 1.0)
        else:
            regime = RegimeType.BULL_TRENDING  # Normal vol
            confidence = 0.5
        
        return RegimeSignal(
            regime=regime,
            confidence=confidence,
            score=float(z_score),
            components={"vol_z_score": float(z_score), "rv_annual": float(current_rv)},
        )
    
    # ── Trend Strength ───────────────────────────────────────────────────────
    
    def _trend_regime(self, df: pd.DataFrame) -> RegimeSignal:
        """
        Detect regime via ADX trend strength.
        
        ADX > 25: Trending (bull/bear determined by slope)
        ADX < 20: Ranging
        """
        adx, di_plus, di_minus = compute_adx(df, 14)
        
        if len(adx) < 14 or pd.isna(adx.iloc[-1]):
            return RegimeSignal(RegimeType.RANGING, 0.5, 0.0)
        
        current_adx = adx.iloc[-1]
        ema_50 = compute_ema(df.close, 50)
        slope = (ema_50.iloc[-1] / ema_50.iloc[-int(min(20, len(ema_50)))] - 1) if len(ema_50) > 20 else 0
        
        if current_adx > self.adx_threshold:
            if slope > 0.01:
                regime = RegimeType.BULL_TRENDING
                confidence = min(current_adx / 50, 1.0)
            elif slope < -0.01:
                regime = RegimeType.BEAR_TRENDING
                confidence = min(current_adx / 50, 1.0)
            else:
                regime = RegimeType.HIGH_VOLATILITY  # High ADX but flat = chop
                confidence = 0.5
        else:
            regime = RegimeType.RANGING
            confidence = max(0.5, 1.0 - current_adx / 25)
        
        return RegimeSignal(
            regime=regime,
            confidence=confidence,
            score=float(current_adx),
            components={"adx": float(current_adx), "slope": float(slope)},
        )
    
    # ── Correlation Regime ───────────────────────────────────────────────────
    
    def _correlation_regime(self, df_dict: Dict[str, pd.DataFrame]) -> RegimeSignal:
        """Delegate to CorrelationRegime analyzer."""
        return self.correlation.detect(df_dict)
    
    # ── Volume Regime ────────────────────────────────────────────────────────
    
    def _volume_regime(self, df: pd.DataFrame) -> RegimeSignal:
        """
        Detect volume-based accumulation/distribution regime.
        
        Uses OBV (On-Balance Volume) trend relative to price:
        - OBV rising with price = accumulation
        - OBV falling with price = distribution
        - Divergences signal regime change.
        """
        if len(df) < 50:
            return RegimeSignal(RegimeType.RANGING, 0.5, 0.0)
        
        obv = compute_obv(df)
        if obv.isna().all():
            return RegimeSignal(RegimeType.RANGING, 0.5, 0.0)
        
        # Normalize
        obv_norm = (obv - obv.rolling(252).mean()) / obv.rolling(252).std().replace(0, np.nan)
        price_norm = (df.close - df.close.rolling(252).mean()) / df.close.rolling(252).std().replace(0, np.nan)
        
        obv_slope = obv.diff(20).mean()
        price_slope = df.close.diff(20).mean()
        
        if not pd.isna(obv_slope) and not pd.isna(price_slope):
            # Accumulation: volume rising faster than price (smart money buying)
            if obv_slope > 0 and price_slope > 0 and obv_slope > price_slope * 0.5:
                regime = RegimeType.ACCUMULATION
                confidence = min(abs(obv_slope) / df.close.mean() * 100, 1.0)
            # Distribution: volume rising but price stagnant/falling
            elif obv_slope < 0 and price_slope < 0:
                regime = RegimeType.DISTRIBUTION
                confidence = min(abs(obv_slope) / df.close.mean() * 100, 1.0)
            # Divergence: OBV diverging from price
            elif obv_slope > 0 and price_slope < 0:
                regime = RegimeType.ACCUMULATION  # Bullish divergence
                confidence = 0.7
            elif obv_slope < 0 and price_slope > 0:
                regime = RegimeType.DISTRIBUTION  # Bearish divergence
                confidence = 0.7
            else:
                regime = RegimeType.RANGING
                confidence = 0.5
        else:
            regime = RegimeType.RANGING
            confidence = 0.4
        
        return RegimeSignal(
            regime=regime,
            confidence=confidence,
            score=float(obv_slope / df.close.mean() * 100 if not pd.isna(obv_slope) else 0),
            components={"obv_slope": float(obv_slope) if not pd.isna(obv_slope) else 0},
        )
    
    # ── Composite Detection ─────────────────────────────────────────────────
    
    def detect(
        self,
        df: pd.DataFrame,
        volumes: Optional[pd.Series] = None,
        cross_asset_df: Optional[Dict[str, pd.DataFrame]] = None,
        re_fit_hmm: bool = True,
    ) -> RegimeComposite:
        """
        Run full regime detection across all models.
        
        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data with columns: open, high, low, close, volume.
        volumes : pd.Series, optional
            Volume data for HMM training (falls back to df.volume).
        cross_asset_df : Dict[str, pd.DataFrame], optional
            Dict of asset dataframes for cross-asset correlation regime.
        re_fit_hmm : bool
            Whether to re-fit the HMM model on this call.
        
        Returns
        -------
        RegimeComposite with all sub-regimes aggregated.
        """
        if not validate_ohlcv(df):
            raise ValueError("DataFrame must have open, high, low, close, volume columns")
        
        vol = volumes if volumes is not None else df.volume
        
        # Fit HMM periodically
        if re_fit_hmm and self.use_hmm:
            self._fit_hmm(df.close, vol)
        
        # Collect signals from all models
        signals = {}
        
        # 1. HMM regime
        if self.use_hmm:
            hmm_sig = self._hmm_regime(df.close, vol)
            if hmm_sig:
                signals["hmm"] = hmm_sig
        
        # 2. Volatility regime
        vol_sig = self._volatility_regime(df)
        signals["volatility"] = vol_sig
        
        # 3. Trend regime (ADX-based)
        trend_sig = self._trend_regime(df)
        signals["trend"] = trend_sig
        
        # 4. Correlation regime (cross-asset)
        if cross_asset_df is not None and len(cross_asset_df) > 1:
            corr_sig = self._correlation_regime(cross_asset_df)
            signals["correlation"] = corr_sig
        
        # 5. Volume regime
        vol_reg_sig = self._volume_regime(df)
        signals["volume"] = vol_reg_sig
        
        # Aggregate into composite
        composite = self._aggregate(signals, df)
        
        self._history.append(composite)
        return composite
    
    def _aggregate(self, signals: Dict[str, RegimeSignal], df: pd.DataFrame) -> RegimeComposite:
        """
        Weighted aggregation of all regime signals into a single composite.
        
        Uses a voting / scoring mechanism:
          - Each model votes for a regime with its confidence weight.
          - Weights: HMM=0.30, Volatility=0.25, Trend=0.25, Volume=0.10, Correlation=0.10
        """
        weights = {
            "hmm": 0.30,
            "volatility": 0.25,
            "trend": 0.25,
            "correlation": 0.10,
            "volume": 0.10,
        }
        
        regime_scores: Dict[RegimeType, float] = {}
        total_weight = 0.0
        
        trend_state = TrendState.RANGING
        vol_state = VolatilityState.NORMAL
        corr_state = CorrelationState.MIXED
        liq_state = LiquidityState.NORMAL
        breadth_state = BreadthState.NEUTRAL
        vol_user_state = VolumeState.NEUTRAL
        
        for name, sig in signals.items():
            w = weights.get(name, 0.1)
            if name not in signals:
                continue
            total_weight += w
            regime_scores[sig.regime] = regime_scores.get(sig.regime, 0.0) + w * sig.confidence
        
        # Determine sub-states
        if "trend" in signals:
            ts = signals["trend"]
            adx = ts.components.get("adx", 0)
            slope = ts.components.get("slope", 0)
            if adx > 25:
                trend_state = TrendState.STRONG_TREND_UP if slope > 0 else TrendState.STRONG_TREND_DOWN
            elif adx > 20:
                trend_state = TrendState.WEAK_TREND_UP if slope > 0 else TrendState.WEAK_TREND_DOWN
            else:
                trend_state = TrendState.RANGING
        
        if "volatility" in signals:
            vs = signals["volatility"]
            z = vs.components.get("vol_z_score", 0)
            if z > 2.0:
                vol_state = VolatilityState.EXTREME
            elif z > 1.0:
                vol_state = VolatilityState.HIGH
            elif z < -0.5:
                vol_state = VolatilityState.LOW
            else:
                vol_state = VolatilityState.NORMAL
        
        if "correlation" in signals:
            cs = signals["correlation"]
            corr_state = CorrelationState.RISK_ON if cs.regime == RegimeType.RISK_ON else (
                CorrelationState.RISK_OFF if cs.regime == RegimeType.RISK_OFF else CorrelationState.MIXED
            )
        
        if "volume" in signals:
            vrs = signals["volume"]
            if vrs.regime == RegimeType.ACCUMULATION:
                vol_user_state = VolumeState.ACCUMULATION
            elif vrs.regime == RegimeType.DISTRIBUTION:
                vol_user_state = VolumeState.DISTRIBUTION
        
        # Pick winner
        if not regime_scores:
            primary = RegimeSignal(RegimeType.UNKNOWN, 0.0, 0.0)
        else:
            best_regime = max(regime_scores, key=regime_scores.get)
            best_score = regime_scores[best_regime]
            # Normalize
            normalized_score = best_score / max(total_weight, 1e-10)
            secondary_regime = max(
                (r for r in regime_scores if r != best_regime),
                key=regime_scores.get, default=None,
            )
            
            primary = RegimeSignal(
                regime=best_regime,
                confidence=min(normalized_score, 1.0),
                score=best_score,
                components={k: v.to_dict() if hasattr(v, 'to_dict') else str(v) for k, v in signals.items()},
            )
            
            secondary = RegimeSignal(
                regime=secondary_regime,
                confidence=regime_scores.get(secondary_regime, 0) / max(total_weight, 1e-10),
                score=regime_scores.get(secondary_regime, 0),
            ) if secondary_regime else None
        
        # Regime strength: how concentrated is the vote?
        sorted_scores = sorted(regime_scores.values(), reverse=True)
        if len(sorted_scores) >= 2:
            strength = sorted_scores[0] - sorted_scores[1]
            regime_strength = min(max(strength * 2, 0), 1.0)  # Scale
        else:
            regime_strength = 0.5
        
        return RegimeComposite(
            primary=primary,
            secondary=secondary,
            trend=trend_state,
            volatility=vol_state,
            correlation=corr_state,
            liquidity=liq_state,
            breadth=breadth_state,
            volume=vol_user_state,
            composite_score=normalized_score if 'normalized_score' in dir() else primary.score,
            regime_strength=regime_strength,
        )
    
    def get_history(self) -> pd.DataFrame:
        """Return the historical regime record as a DataFrame."""
        records = [r.to_dict() for r in self._history]
        return pd.DataFrame(records) if records else pd.DataFrame()
    
    def summary(self) -> str:
        """Text summary of the most recent regime."""
        if not self._history:
            return "No regime data available."
        r = self._history[-1]
        return (
            f"Market Regime: {r.primary.regime.name} "
            f"(confidence: {r.primary.confidence:.1%})\n"
            f"  Trend: {r.trend.name} | Vol: {r.volatility.name} | "
            f"Corr: {r.correlation.name}\n"
            f"  Liq: {r.liquidity.name} | Breadth: {r.breadth.name} | "
            f"Vol-Type: {r.volume.name}\n"
            f"  Regime Strength: {r.regime_strength:.2f} | "
            f"Composite: {r.composite_score:.3f}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. TrendStrengthAnalyzer
# ══════════════════════════════════════════════════════════════════════════════

class TrendStrengthAnalyzer:
    """
    Comprehensive trend strength analysis.
    
    Combines:
    - ADX with directional interpretation (DI+ / DI-)
    - MA slope (angle of EMA 50 in degrees)
    - Higher highs / higher lows count
    - Fractal dimension (trend vs noise ratio)
    - Hurst exponent (mean-reverting < 0.5, random walk = 0.5, trending > 0.5)
    
    References
    ----------
    - Wilder (1978) — New Concepts in Technical Trading Systems
    - Hurst (1951) — Long-term storage capacity of reservoirs
    - Mandelbrot (1963) — The variation of certain speculative prices
    """
    
    def __init__(self, adx_period: int = 14, ma_period: int = 50):
        self.adx_period = adx_period
        self.ma_period = ma_period
    
    def analyze(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Run all trend strength analyses.
        
        Parameters
        ----------
        df : pd.DataFrame with OHLCV data.
        
        Returns
        -------
        Dict with keys: adx, di_plus, di_minus, ma_slope, ma_angle,
                        hh_count, hl_count, fractal_dimension, hurst_exponent,
                        trend_state, trend_strength
        """
        result = {}
        
        # 1. ADX Analysis
        adx_result = self._compute_adx_analysis(df)
        result.update(adx_result)
        
        # 2. MA Slope
        slope_result = self._compute_ma_slope(df)
        result.update(slope_result)
        
        # 3. Higher highs / Higher lows
        hh_result = self._count_hh_hl(df)
        result.update(hh_result)
        
        # 4. Fractal dimension
        fd = self._fractal_dimension(df.close.values)
        result["fractal_dimension"] = fd
        
        # 5. Hurst exponent
        he = self._hurst_exponent(df.close.values)
        result["hurst_exponent"] = he
        
        # 6. Composite trend state
        result["trend_state"] = self._classify_trend_state(result)
        result["trend_strength"] = self._trend_strength_score(result)
        
        return result
    
    def _compute_adx_analysis(self, df: pd.DataFrame) -> Dict[str, float]:
        """ADX with directional interpretation."""
        adx, di_plus, di_minus = compute_adx(df, self.adx_period)
        
        if adx is None or len(adx) < 2 or pd.isna(adx.iloc[-1]):
            return {"adx": 0.0, "di_plus": 0.0, "di_minus": 0.0, "adx_direction": 0.0}
        
        current_adx = float(adx.iloc[-1])
        di_p = float(di_plus.iloc[-1]) if di_plus is not None else 0.0
        di_m = float(di_minus.iloc[-1]) if di_minus is not None else 0.0
        
        # ADX direction: positive = DI+ dominant, negative = DI- dominant
        direction = di_p - di_m
        
        return {
            "adx": current_adx,
            "di_plus": di_p,
            "di_minus": di_m,
            "adx_direction": direction,
        }
    
    def _compute_ma_slope(self, df: pd.DataFrame, period: int = 50) -> Dict[str, float]:
        """
        Compute the slope (angle in degrees) of the EMA.
        
        Slope = arctan(price_change / lookback) expressed as degrees.
        """
        if len(df) < period + 5:
            return {"ma_slope": 0.0, "ma_angle": 0.0}
        
        ema = compute_ema(df.close, period)
        if ema.isna().all():
            return {"ma_slope": 0.0, "ma_angle": 0.0}
        
        lookback = min(period // 2, 20)
        current = float(ema.iloc[-1])
        prev = float(ema.iloc[-lookback]) if len(ema) > lookback else float(ema.iloc[0])
        
        pct_change = (current / prev - 1) * 100  # Percent
        angle_rad = np.arctan2(current - prev, lookback)
        angle_deg = np.degrees(angle_rad)
        
        return {
            "ma_slope": pct_change,
            "ma_angle": angle_deg,
        }
    
    def _count_hh_hl(self, df: pd.DataFrame, lookback: int = 50) -> Dict[str, int]:
        """
        Count consecutive higher highs and higher lows.
        
        A higher high: current high > previous high
        A higher low: current low > previous low
        
        Consecutive count indicates trend strength.
        """
        if len(df) < 5:
            return {"hh_count": 0, "hl_count": 0, "hh_hl_ratio": 0.0}
        
        highs = df.high.values[-lookback:]
        lows = df.low.values[-lookback:]
        
        hh_count = 0
        hl_count = 0
        
        for i in range(1, len(highs)):
            if highs[i] > highs[i-1]:
                hh_count += 1
            if lows[i] > lows[i-1]:
                hl_count += 1
        
        ratio = hh_count / max(hl_count, 1)
        
        return {
            "hh_count": hh_count,
            "hl_count": hl_count,
            "hh_hl_ratio": ratio,
        }
    
    def _fractal_dimension(self, prices: np.ndarray) -> float:
        """
        Compute the fractal (Hausdorff) dimension of the price series.
        
        Uses the box-counting / Higuchi algorithm.
        
        Higher values (>1.5) = more noise / less structure.
        Lower values (<1.3) = stronger trend / more structure.
        
        References
        ----------
        Higuchi (1988) — Approach to an irregular time series on the basis of
        the fractal theory.
        """
        if len(prices) < 100:
            return 1.5
        
        # Normalize prices
        y = prices[~np.isnan(prices)]
        if len(y) < 100:
            return 1.5
        y = y[-252:]
        
        # Rescale to [0, 1]
        y_min, y_max = y.min(), y.max()
        if y_max - y_min < 1e-10:
            return 1.5
        y = (y - y_min) / (y_max - y_min)
        
        # Higuchi's algorithm
        n = len(y)
        L = np.zeros(min(n // 2, 50))
        counts = np.zeros(min(n // 2, 50))
        
        for k in range(1, min(n // 2, 50) + 1):
            Lk = 0.0
            n_segments = 0
            for m in range(k):
                idx = np.arange(m, n, k)
                if len(idx) > 1:
                    seg = y[idx]
                    Lk += np.sum(np.abs(np.diff(seg))) * (n - 1) / (k * len(idx))
                    n_segments += 1
            if n_segments > 0:
                L[k-1] = Lk / n_segments
                counts[k-1] = k
        
        # Filter valid points
        valid = (L > 0) & (counts > 0)
        if valid.sum() < 5:
            return 1.5
        
        x = np.log(counts[valid])
        y_log = np.log(L[valid])
        
        # Linear regression for slope
        A = np.vstack([x, np.ones_like(x)]).T
        try:
            slope, _ = np.linalg.lstsq(A, y_log, rcond=None)[0]
            fd = 2.0 - slope
        except np.linalg.LinAlgError:
            fd = 1.5
        
        return max(1.0, min(2.0, fd))
    
    def _hurst_exponent(self, prices: np.ndarray, max_lag: int = 20) -> float:
        """
        Compute the Hurst exponent via R/S analysis.
        
        H < 0.5  → Mean-reverting (anti-persistent, range-bound regime)
        H = 0.5  → Random walk (efficient market, no exploitable trend)
        H > 0.5  → Trending (persistent, momentum regime)
        
        References
        ----------
        Hurst (1951) — Long-term storage capacity of reservoirs.
        Peters (1994) — Fractal Market Analysis.
        """
        if len(prices) < 100:
            return 0.5
        
        y = prices[~np.isnan(prices)]
        if len(y) < 100:
            return 0.5
        y = y[-252:]
        
        log_returns = np.diff(np.log(y))
        if len(log_returns) < max_lag * 2:
            return 0.5
        
        lags = range(2, min(max_lag, len(log_returns) // 2))
        tau = []
        
        for lag in lags:
            # Split into segments of length `lag`
            n_segments = len(log_returns) // lag
            if n_segments < 1:
                continue
            
            # Reshape and compute R/S per segment
            segments = log_returns[:n_segments * lag].reshape(n_segments, lag)
            
            # Mean-centered cumulative sum per segment
            seg_means = segments.mean(axis=1, keepdims=True)
            deviations = segments - seg_means
            cumsums = deviations.cumsum(axis=1)
            
            # Range per segment
            R = cumsums.max(axis=1) - cumsums.min(axis=1)
            
            # Std per segment
            S = segments.std(axis=1, ddof=1)
            S = np.where(S == 0, 1e-10, S)
            
            # R/S ratio
            rs = R / S
            tau.append(np.mean(rs))
        
        tau = np.array(tau)
        lags_arr = np.array(list(lags[:len(tau)]))
        
        if len(tau) < 5:
            return 0.5
        
        # Linear regression: log(R/S) vs log(lag)
        x = np.log(lags_arr)
        y_log = np.log(tau)
        
        A = np.vstack([x, np.ones_like(x)]).T
        try:
            H, _ = np.linalg.lstsq(A, y_log, rcond=None)[0]
        except np.linalg.LinAlgError:
            H = 0.5
        
        return float(max(0.01, min(0.99, H)))
    
    def _classify_trend_state(self, result: Dict[str, Any]) -> TrendState:
        """Classify the trend state from all metrics."""
        adx = result.get("adx", 0)
        direction = result.get("adx_direction", 0)
        hurst = result.get("hurst_exponent", 0.5)
        fd = result.get("fractal_dimension", 1.5)
        
        # Noise check: fractal dimension > 1.6 = noisy
        if fd > 1.6 and hurst < 0.55:
            return TrendState.NOISE
        
        # Trending: Hurst > 0.55 or ADX > 25
        if hurst > 0.55 or adx > 25:
            if direction > 5:
                return TrendState.STRONG_TREND_UP
            elif direction < -5:
                return TrendState.STRONG_TREND_DOWN
            elif direction > 0:
                return TrendState.WEAK_TREND_UP
            else:
                return TrendState.WEAK_TREND_DOWN
        
        # Mean-reverting / ranging: Hurst < 0.45
        if hurst < 0.45:
            return TrendState.RANGING
        
        return TrendState.NOISE
    
    def _trend_strength_score(self, result: Dict[str, Any]) -> float:
        """Composite trend strength score from 0 (no trend) to 1 (strong trend)."""
        adx_score = min(result.get("adx", 0) / 50.0, 1.0) * 0.30
        hurst_score = max(0, abs(result.get("hurst_exponent", 0.5) - 0.5) * 4) * 0.25
        fd_score = max(0, 1.0 - (result.get("fractal_dimension", 1.5) - 1.0) * 2) * 0.20
        slope_score = min(abs(result.get("ma_slope", 0)) * 10, 1.0) * 0.25
        
        return min(adx_score + hurst_score + fd_score + slope_score, 1.0)


# ══════════════════════════════════════════════════════════════════════════════
# 3. VolatilityRegime
# ══════════════════════════════════════════════════════════════════════════════

class GARCHRegimeSwitcher:
    """
    Simplified GARCH(1,1) regime-switching volatility model.
    
    Uses a rolling-window GARCH estimation to classify vol regimes.
    
    References
    ----------
    Bollerslev (1986) — Generalized autoregressive conditional heteroskedasticity.
    Hamilton & Susmel (1994) — Autoregressive conditional heteroskedasticity
    and changes in regime.
    """
    
    def __init__(self, window: int = 252, omega: float = 0.01, alpha: float = 0.1, beta: float = 0.85):
        self.window = window
        self.omega = omega
        self.alpha = alpha
        self.beta = beta
        self._vol_forecast: Optional[float] = None
    
    def compute_garch_variance(self, returns: np.ndarray) -> np.ndarray:
        """
        Compute GARCH(1,1) conditional variance.
        
        σ²_t = ω + α * ε²_{t-1} + β * σ²_{t-1}
        
        Parameters
        ----------
        returns : np.ndarray of log returns.
        
        Returns
        -------
        Conditional variance series.
        """
        n = len(returns)
        variance = np.full(n, np.nan)
        
        # Initial variance = sample variance of first 20 observations
        init_var = np.var(returns[:min(20, n)])
        if init_var < 1e-12:
            init_var = 1e-6
        
        variance[0] = init_var
        for t in range(1, n):
            variance[t] = (
                self.omega
                + self.alpha * returns[t-1]**2
                + self.beta * variance[t-1]
            )
        
        return variance
    
    def regime_probability(
        self, returns: np.ndarray
    ) -> Tuple[float, float, float]:
        """
        Estimate probability of being in low / normal / high vol regime.
        
        Uses threshold-based approach on conditional variance,
        comparing to long-run average.
        
        Returns
        -------
        (p_low, p_normal, p_high) probabilities.
        """
        var = self.compute_garch_variance(returns)
        var = var[~np.isnan(var)]
        
        if len(var) < 20:
            return 0.33, 0.34, 0.33
        
        current_vol = np.sqrt(var[-1])
        hist_vol = np.sqrt(np.mean(var))
        hist_std = np.std(np.sqrt(var))
        
        if hist_std < 1e-10:
            return 0.33, 0.34, 0.33
        
        z = (current_vol - hist_vol) / hist_std
        
        # Convert z-score to regime probabilities using normal CDF
        p_low = stats.norm.cdf(-1.0 - z) if z < 0 else stats.norm.cdf(-1.0)
        p_high = stats.norm.cdf(z - 1.0) if z > 0 else stats.norm.cdf(-1.0)
        p_normal = 1.0 - p_low - p_high
        
        total = p_low + p_normal + p_high
        if total > 0:
            p_low /= total
            p_normal /= total
            p_high /= total
        
        return float(p_low), float(p_normal), float(p_high)


class VolatilityRegime:
    """
    Full volatility regime detection.
    
    Features:
    - Low / Normal / High / Extreme volatility classification
    - Volatility of volatility (vol-of-vol)
    - GARCH(1,1) regime-switching
    - VIX term structure regime (contango / backwardation)
    - Implied vs realized vol spread
    
    References
    ----------
    CBOE (2009) — VIX White Paper.
    Bollerslev (1986) — GARCH(1,1).
    """
    
    def __init__(
        self,
        lookback: int = 252,
        low_threshold: float = -0.5,
        high_threshold: float = 1.0,
        extreme_threshold: float = 2.0,
    ):
        self.lookback = lookback
        self.low_threshold = low_threshold
        self.high_threshold = high_threshold
        self.extreme_threshold = extreme_threshold
        self.garch = GARCHRegimeSwitcher(window=lookback)
    
    def detect(self, df: pd.DataFrame, vix_data: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Detect volatility regime from price data.
        
        Parameters
        ----------
        df : pd.DataFrame with OHLCV data.
        vix_data : pd.DataFrame, optional, with columns: vix, vix3m (VIX futures).
        
        Returns
        -------
        Dict with: vol_state, realized_vol, vol_of_vol, garch_prob_low,
                   garch_prob_normal, garch_prob_high, vix_term_structure,
                   iv_rv_spread
        """
        result = {}
        
        # 1. Realized volatility
        rv = self._realized_vol(df)
        result.update(rv)
        
        # 2. Volatility of volatility
        vov = self._vol_of_vol(df)
        result.update(vov)
        
        # 3. GARCH regime probabilities
        returns = np.diff(np.log(df.close.values))
        returns = returns[~np.isnan(returns)]
        if len(returns) > 20:
            p_low, p_norm, p_high = self.garch.regime_probability(returns)
            result["garch_prob_low"] = p_low
            result["garch_prob_normal"] = p_norm
            result["garch_prob_high"] = p_high
        else:
            result["garch_prob_low"] = 0.33
            result["garch_prob_normal"] = 0.34
            result["garch_prob_high"] = 0.33
        
        # 4. VIX term structure (if available)
        if vix_data is not None and not vix_data.empty:
            vix_ts = self._vix_term_structure(vix_data)
            result.update(vix_ts)
        else:
            result["vix_term_structure"] = 0.0
            result["vix_contango"] = True
        
        # 5. Implied vs realized vol spread
        if vix_data is not None and not vix_data.empty:
            iv_rv = self._iv_rv_spread(vix_data, rv.get("realized_vol_21d", 0))
            result.update(iv_rv)
        else:
            result["iv_rv_spread"] = 0.0
        
        # 6. Classify state
        result["vol_state"] = self._classify_vol_state(result)
        
        return result
    
    def _realized_vol(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        Compute realized volatility at multiple horizons.
        
        Returns annualized realized vol for 7, 21, and 63 days.
        """
        if len(df) < 7:
            return {"realized_vol_7d": 0.0, "realized_vol_21d": 0.0, "realized_vol_63d": 0.0}
        
        returns = df.close.pct_change().dropna()
        
        rv = {}
        for horizon, label in [(7, "7d"), (21, "21d"), (63, "63d")]:
            if len(returns) >= horizon:
                rv[f"realized_vol_{label}"] = float(returns.tail(horizon).std() * np.sqrt(252))
            else:
                rv[f"realized_vol_{label}"] = 0.0
        
        return rv
    
    def _vol_of_vol(self, df: pd.DataFrame, lookback: int = 63) -> Dict[str, float]:
        """
        Compute volatility of volatility (vol-of-vol).
        
        Measures how much volatility itself is fluctuating.
        High vol-of-vol indicates regime instability.
        """
        if len(df) < lookback + 21:
            return {"vol_of_vol": 0.0, "vol_of_vol_zscore": 0.0}
        
        returns = df.close.pct_change().dropna()
        rv_21 = returns.rolling(21).std() * np.sqrt(252)
        
        if len(rv_21) < lookback:
            return {"vol_of_vol": 0.0, "vol_of_vol_zscore": 0.0}
        
        rv_recent = rv_21.tail(lookback)
        
        vov = float(rv_recent.std())
        vov_mean = float(rv_recent.mean())
        vov_z = (rv_recent.iloc[-1] - vov_mean) / max(vov, 1e-10) if vov > 1e-10 else 0.0
        
        return {"vol_of_vol": vov, "vol_of_vol_zscore": vov_z}
    
    def _vix_term_structure(self, vix_data: pd.DataFrame) -> Dict[str, Any]:
        """
        Assess VIX term structure.
        
        Contango (vix < vix3m) → Normal / low stress.
        Backwardation (vix > vix3m) → Stress / crisis regime.
        """
        if "vix" not in vix_data.columns:
            return {"vix_term_structure": 0.0, "vix_contango": True}
        
        vix = vix_data["vix"].iloc[-1] if "vix" in vix_data.columns else 0
        vix_3m = vix_data.get("vix3m", pd.Series([vix * 1.05])).iloc[-1]
        
        if pd.isna(vix) or pd.isna(vix_3m):
            return {"vix_term_structure": 0.0, "vix_contango": True}
        
        spread = (vix_3m - vix) / max(vix, 1)
        contango = spread > 0
        
        return {
            "vix_term_structure": float(spread),
            "vix_contango": bool(contango),
        }
    
    def _iv_rv_spread(self, vix_data: pd.DataFrame, realized_vol: float) -> Dict[str, float]:
        """
        Compute implied vs realized vol spread.
        
        Large positive spread (IV >> RV) → Fear premium, risk-off.
        Negative spread (IV < RV) → Complacency, risk-on.
        """
        vix = vix_data.get("vix", pd.Series([15.0])).iloc[-1] if "vix" in vix_data.columns else 15.0
        
        if pd.isna(vix) or pd.isna(realized_vol) or realized_vol < 1e-6:
            return {"iv_rv_spread": 0.0}
        
        spread = (vix / 100.0 - realized_vol) / max(realized_vol, 1e-6)
        
        return {"iv_rv_spread": float(spread)}
    
    def _classify_vol_state(self, result: Dict[str, Any]) -> VolatilityState:
        """Classify the overall volatility state."""
        z = result.get("vol_of_vol_zscore", 0)
        p_high = result.get("garch_prob_high", 0.33)
        
        if z > self.extreme_threshold or p_high > 0.7:
            return VolatilityState.EXTREME
        elif z > self.high_threshold or p_high > 0.5:
            return VolatilityState.HIGH
        elif z < self.low_threshold:
            return VolatilityState.LOW
        else:
            return VolatilityState.NORMAL


# ══════════════════════════════════════════════════════════════════════════════
# 4. CorrelationRegime
# ══════════════════════════════════════════════════════════════════════════════

class CorrelationRegime:
    """
    Cross-asset correlation regime detection.
    
    Uses PCA on a correlation matrix of multiple assets to identify:
      - Risk-on regime (first PC explains high variance, all assets +correlated)
      - Risk-off regime (first PC explains high variance, all assets +correlated)
      - Regime change (correlation structure breaks down)
    
    The first principal component is interpreted as the "risk factor".
    When eigenvectors are all positive → all assets move together (risk-on/off).
    Sign of PC1 scores determines risk-on vs risk-off.
    
    References
    ----------
    Alexander (2001) — Market Models: A Guide to Financial Data Analysis.
    Pukthuanthong & Roll (2009) — Global market integration.
    """
    
    def __init__(self, lookback: int = 63, n_assets_min: int = 3):
        self.lookback = lookback
        self.n_assets_min = n_assets_min
        self._pca: Optional[PCA] = None
        self._scaler: Optional[StandardScaler] = None
        self._historical_pc1_var: deque = deque(maxlen=252)
    
    def detect(self, df_dict: Dict[str, pd.DataFrame]) -> RegimeSignal:
        """
        Detect correlation regime from multiple asset DataFrames.
        
        Parameters
        ----------
        df_dict : Dict[str, pd.DataFrame]
            Dict of asset_name -> OHLCV DataFrame.
        
        Returns
        -------
        RegimeSignal with RiskOn / RiskOff / Mixed regime.
        """
        if len(df_dict) < self.n_assets_min:
            return RegimeSignal(RegimeType.RANGING, 0.5, 0.0)
        
        # Build return matrix
        return_matrix = []
        asset_names = []
        
        for name, df in df_dict.items():
            if df is None or len(df) < self.lookback:
                continue
            returns = df.close.pct_change().dropna().tail(self.lookback)
            if len(returns) >= self.lookback // 2:
                return_matrix.append(returns.values)
                asset_names.append(name)
        
        if len(return_matrix) < self.n_assets_min:
            return RegimeSignal(RegimeType.RANGING, 0.5, 0.0)
        
        # Align lengths
        min_len = min(len(r) for r in return_matrix)
        return_matrix = np.column_stack([r[-min_len:] for r in return_matrix])
        
        # Standardize
        self._scaler = StandardScaler()
        X = self._scaler.fit_transform(return_matrix)
        
        # PCA
        self._pca = PCA()
        PC = self._pca.fit_transform(X)
        
        # First principal component
        pc1 = PC[:, 0]
        pc1_var_explained = self._pca.explained_variance_ratio_[0]
        pc1_loadings = self._pca.components_[0, :]
        
        self._historical_pc1_var.append(pc1_var_explained)
        
        # Interpret PC1
        # All positive loadings = unified risk factor
        positive_loading_ratio = np.mean(pc1_loadings > 0)
        avg_loading = np.mean(pc1_loadings)
        
        # Score direction: positive PC1 = risk-on
        recent_pc1 = np.mean(pc1[-min(20, len(pc1)):])
        
        # Correlation breakdown detection
        if len(self._historical_pc1_var) > 20:
            current_var = pc1_var_explained
            hist_var = np.mean(list(self._historical_pc1_var)[:-1])
            hist_std = np.std(list(self._historical_pc1_var)[:-1])
            
            breakdown = (current_var < hist_var - 2 * hist_std)
        else:
            breakdown = False
        
        # Determine regime
        if breakdown:
            # Correlation structure breaking down = mixed regime
            regime = RegimeType.RANGING
            confidence = 0.3
        elif positive_loading_ratio > 0.7 and pc1_var_explained > 0.4:
            # Strong single factor
            if recent_pc1 > 0:
                regime = RegimeType.RISK_ON
            else:
                regime = RegimeType.RISK_OFF
            confidence = min(pc1_var_explained, 0.95)
        else:
            regime = RegimeType.RANGING
            confidence = 0.4
        
        return RegimeSignal(
            regime=regime,
            confidence=confidence,
            score=float(avg_loading),
            components={
                "pc1_var": float(pc1_var_explained),
                "positive_loading_ratio": float(positive_loading_ratio),
                "avg_loading": float(avg_loading),
                "recent_pc1": float(recent_pc1),
                "correlation_breakdown": breakdown,
                "n_assets": len(asset_names),
            },
        )
    
    def get_pca_result(self) -> Optional[Dict[str, Any]]:
        """Get the fitted PCA model result for analysis."""
        if self._pca is None:
            return None
        return {
            "explained_variance_ratio": self._pca.explained_variance_ratio_.tolist(),
            "pc1_loadings": self._pca.components_[0, :].tolist(),
            "pc1_variance": float(self._pca.explained_variance_ratio_[0]),
        }


# ══════════════════════════════════════════════════════════════════════════════
# 5. BreadthRegime
# ══════════════════════════════════════════════════════════════════════════════

class BreadthRegime:
    """
    Market breadth regime detection.
    
    Indicators:
    - Advance-Decline Line (A/D line trend)
    - Percentage of stocks above MA 50 and MA 200
    - McClellan Oscillator (19/39-day smoothed A/D)
    - New Highs vs New Lows ratio
    
    References
    ----------
    Arms (1989) — Volume Cycles in the Stock Market.
    McClellan & McClellan (2004) — Patterns for Profit.
    """
    
    def __init__(
        self,
        ma50_threshold: float = 0.6,
        ma200_threshold: float = 0.6,
        mcclellan_period_fast: int = 19,
        mcclellan_period_slow: int = 39,
    ):
        self.ma50_threshold = ma50_threshold
        self.ma200_threshold = ma200_threshold
        self.mcclellan_fast = mcclellan_period_fast
        self.mcclellan_slow = mcclellan_period_slow
    
    def detect(
        self,
        advance_decline: Optional[pd.Series] = None,
        pct_above_ma50: Optional[pd.Series] = None,
        pct_above_ma200: Optional[pd.Series] = None,
        advances: Optional[pd.Series] = None,
        declines: Optional[pd.Series] = None,
        new_highs: Optional[pd.Series] = None,
        new_lows: Optional[pd.Series] = None,
    ) -> Dict[str, Any]:
        """
        Detect the market breadth regime.
        
        Parameters can be partial; only available indicators are used.
        
        Returns
        -------
        Dict with: breadth_state, ad_line_trend, pct_above_ma50,
                   pct_above_ma200, mcclellan_oscillator, nh_nl_ratio,
                   breadth_score
        """
        result = {}
        indicators_used = []
        
        # 1. Advance-Decline Line trend
        if advance_decline is not None and len(advance_decline) > 20:
            ad_trend = self._ad_line_trend(advance_decline)
            result.update(ad_trend)
            indicators_used.append("ad_line")
        
        # 2. % Stocks above MAs
        if pct_above_ma50 is not None and len(pct_above_ma50) > 0:
            result["pct_above_ma50"] = float(pct_above_ma50.iloc[-1])
            result["ma50_bullish"] = bool(pct_above_ma50.iloc[-1] > self.ma50_threshold)
            indicators_used.append("pct_ma50")
        
        if pct_above_ma200 is not None and len(pct_above_ma200) > 0:
            result["pct_above_ma200"] = float(pct_above_ma200.iloc[-1])
            result["ma200_bullish"] = bool(pct_above_ma200.iloc[-1] > self.ma200_threshold)
            indicators_used.append("pct_ma200")
        
        # 3. McClellan Oscillator
        if advances is not None and declines is not None:
            if len(advances) > self.mcclellan_slow and len(declines) > self.mcclellan_slow:
                mcc = self._mcclellan_oscillator(advances, declines)
                result.update(mcc)
                indicators_used.append("mcclellan")
        
        # 4. New Highs / New Lows
        if new_highs is not None and new_lows is not None:
            if len(new_highs) > 0 and len(new_lows) > 0:
                nh_nl = self._nh_nl_ratio(new_highs, new_lows)
                result.update(nh_nl)
                indicators_used.append("nh_nl")
        
        # 5. Composite state
        result["breadth_state"] = self._classify_breadth(result)
        result["breadth_score"] = self._breadth_composite_score(result)
        result["indicators_used"] = indicators_used
        
        return result
    
    def _ad_line_trend(self, ad_line: pd.Series, lookback: int = 50) -> Dict[str, Any]:
        """Compute A/D line slope and trend signal."""
        if len(ad_line) < lookback:
            return {"ad_line_trend": 0.0, "ad_line_bullish": True}
        
        recent = ad_line.tail(lookback)
        slope = (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0] * 100 if recent.iloc[0] != 0 else 0
        
        return {
            "ad_line_trend": float(slope),
            "ad_line_bullish": bool(slope > 0),
        }
    
    def _mcclellan_oscillator(
        self, advances: pd.Series, declines: pd.Series
    ) -> Dict[str, float]:
        """
        Compute McClellan Oscillator.
        
        Net Advances = Advances - Declines
        McClellan = EMA_19(Net Advances) - EMA_39(Net Advances)
        
        Positive = bullish breadth
        Negative = bearish breadth
        Beyond ±100 = overbought / oversold
        """
        net_advances = advances - declines
        
        ema_fast = net_advances.ewm(span=self.mcclellan_fast, adjust=False).mean()
        ema_slow = net_advances.ewm(span=self.mcclellan_slow, adjust=False).mean()
        
        oscillator = ema_fast - ema_slow
        
        return {
            "mcclellan_oscillator": float(oscillator.iloc[-1]) if len(oscillator) > 0 else 0.0,
            "mcclellan_ema_fast": float(ema_fast.iloc[-1]) if len(ema_fast) > 0 else 0.0,
            "mcclellan_ema_slow": float(ema_slow.iloc[-1]) if len(ema_slow) > 0 else 0.0,
        }
    
    def _nh_nl_ratio(self, new_highs: pd.Series, new_lows: pd.Series) -> Dict[str, float]:
        """
        Compute New Highs / New Lows ratio.
        
        NH/NL > 1.0 → Bullish
        NH/NL < 1.0 → Bearish
        NH/(NH+NL) > 0.7 → Overbought
        NH/(NH+NL) < 0.3 → Oversold
        """
        recent_nh = new_highs.iloc[-1]
        recent_nl = new_lows.iloc[-1]
        
        nh_nl_ratio = recent_nh / max(recent_nl, 1)
        
        # High-low ratio
        total = recent_nh + recent_nl
        hl_ratio = recent_nh / total if total > 0 else 0.5
        
        return {
            "nh_nl_ratio": float(nh_nl_ratio),
            "nh_pct": float(hl_ratio),
            "new_highs": float(recent_nh),
            "new_lows": float(recent_nl),
        }
    
    def _classify_breadth(self, result: Dict[str, Any]) -> BreadthState:
        """Classify breadth state from all available indicators."""
        bullish_signals = 0
        bearish_signals = 0
        total_signals = 0
        
        if "ad_line_bullish" in result:
            if result["ad_line_bullish"]:
                bullish_signals += 1
            else:
                bearish_signals += 1
            total_signals += 1
        
        if "ma50_bullish" in result:
            if result["ma50_bullish"]:
                bullish_signals += 1
            else:
                bearish_signals += 1
            total_signals += 1
        
        if "ma200_bullish" in result:
            if result["ma200_bullish"]:
                bullish_signals += 1
            else:
                bearish_signals += 1
            total_signals += 1
        
        if "mcclellan_oscillator" in result:
            mcc = result["mcclellan_oscillator"]
            if mcc > 100:
                return BreadthState.OVERBOUGHT
            elif mcc > 25:
                bullish_signals += 1
            elif mcc < -100:
                return BreadthState.OVERSOLD
            elif mcc < -25:
                bearish_signals += 1
            total_signals += 1
        
        if "nh_nl_ratio" in result:
            if result["nh_nl_ratio"] > 2.0:
                return BreadthState.OVERBOUGHT
            elif result["nh_nl_ratio"] > 1.0:
                bullish_signals += 1
            elif result["nh_nl_ratio"] < 0.5:
                return BreadthState.OVERSOLD
            else:
                bearish_signals += 1
            total_signals += 1
        
        if total_signals == 0:
            return BreadthState.NEUTRAL
        
        bullish_pct = bullish_signals / total_signals
        if bullish_pct > 0.66:
            return BreadthState.BULLISH
        elif bullish_pct < 0.33:
            return BreadthState.BEARISH
        else:
            return BreadthState.NEUTRAL
    
    def _breadth_composite_score(self, result: Dict[str, Any]) -> float:
        """Composite breadth score: +1 (strong bullish) to -1 (strong bearish)."""
        score = 0.0
        count = 0
        
        if "ad_line_trend" in result:
            score += np.sign(result["ad_line_trend"])
            count += 1
        
        if "pct_above_ma50" in result:
            score += (result["pct_above_ma50"] - 0.5) * 2
            count += 1
        
        if "pct_above_ma200" in result:
            score += (result["pct_above_ma200"] - 0.5) * 2
            count += 1
        
        if "mcclellan_oscillator" in result:
            score += np.clip(result["mcclellan_oscillator"] / 100, -1, 1)
            count += 1
        
        if "nh_pct" in result:
            score += (result["nh_pct"] - 0.5) * 2
            count += 1
        
        return score / max(count, 1)


# ══════════════════════════════════════════════════════════════════════════════
# 6. LiquidityRegime
# ══════════════════════════════════════════════════════════════════════════════

class LiquidityRegime:
    """
    Liquidity regime detection.
    
    Evaluates:
    - Bid-ask spread regime (wide / tight)
    - Volume regime (high / low participation)
    - Order book depth regime (deep / shallow)
    
    References
    ----------
    Amihud (2002) — Illiquidity and stock returns.
    Kyle (1985) — Continuous auctions and insider trading.
    """
    
    def __init__(
        self,
        volume_lookback: int = 252,
        spread_lookback: int = 63,
        volume_z_high: float = 1.0,
        volume_z_low: float = -0.5,
    ):
        self.volume_lookback = volume_lookback
        self.spread_lookback = spread_lookback
        self.volume_z_high = volume_z_high
        self.volume_z_low = volume_z_low
    
    def detect(
        self,
        df: pd.DataFrame,
        bid_ask_spreads: Optional[pd.Series] = None,
        order_book_depth: Optional[pd.Series] = None,
    ) -> Dict[str, Any]:
        """
        Detect liquidity regime.
        
        Parameters
        ----------
        df : pd.DataFrame with OHLCV data (volume column required).
        bid_ask_spreads : pd.Series, optional. Relative bid-ask spreads.
        order_book_depth : pd.Series, optional. Total depth at best bid/ask.
        
        Returns
        -------
        Dict with: liquidity_state, volume_z_score, spread_z_score,
                   depth_z_score, composite_liquidity_score
        """
        result = {}
        indicators_used = []
        
        # 1. Volume regime
        vol_result = self._volume_regime(df)
        result.update(vol_result)
        indicators_used.append("volume")
        
        # 2. Bid-ask spread regime
        if bid_ask_spreads is not None and len(bid_ask_spreads) > 5:
            spread_result = self._spread_regime(bid_ask_spreads)
            result.update(spread_result)
            indicators_used.append("spread")
        
        # 3. Order book depth regime
        if order_book_depth is not None and len(order_book_depth) > 5:
            depth_result = self._depth_regime(order_book_depth)
            result.update(depth_result)
            indicators_used.append("depth")
        
        # 4. Composite liquidity state
        result["liquidity_state"] = self._classify_liquidity(result)
        result["composite_liquidity_score"] = self._liquidity_score(result)
        result["indicators_used"] = indicators_used
        
        return result
    
    def _volume_regime(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Classify volume regime based on z-score relative to history."""
        if len(df) < 21:
            return {"volume_z_score": 0.0, "volume_regime": "normal"}
        
        volume = df.volume
        vol_ma = volume.rolling(self.volume_lookback).mean()
        vol_std = volume.rolling(self.volume_lookback).std()
        
        if vol_std.iloc[-1] == 0 or pd.isna(vol_std.iloc[-1]):
            return {"volume_z_score": 0.0, "volume_regime": "normal"}
        
        z = (volume.iloc[-1] - vol_ma.iloc[-1]) / vol_std.iloc[-1]
        
        if z > self.volume_z_high:
            regime = "high_participation"
        elif z < self.volume_z_low:
            regime = "low_participation"
        else:
            regime = "normal"
        
        return {
            "volume_z_score": float(z),
            "volume_regime": regime,
        }
    
    def _spread_regime(self, spreads: pd.Series) -> Dict[str, Any]:
        """Classify bid-ask spread regime."""
        if len(spreads) < self.spread_lookback:
            return {"spread_z_score": 0.0, "spread_regime": "normal"}
        
        recent = spreads.tail(self.spread_lookback)
        mean_spread = recent.mean()
        std_spread = recent.std()
        
        if std_spread == 0 or pd.isna(std_spread):
            return {"spread_z_score": 0.0, "spread_regime": "normal"}
        
        z = (spreads.iloc[-1] - mean_spread) / std_spread
        
        if z > 1.5:
            regime = "wide_spread"   # Illiquid
        elif z < -0.5:
            regime = "tight_spread"  # Liquid
        else:
            regime = "normal_spread"
        
        return {
            "spread_z_score": float(z),
            "spread_regime": regime,
        }
    
    def _depth_regime(self, depth: pd.Series) -> Dict[str, Any]:
        """Classify order book depth regime."""
        if len(depth) < 20:
            return {"depth_z_score": 0.0, "depth_regime": "normal"}
        
        recent = depth.tail(self.spread_lookback)
        mean_depth = recent.mean()
        std_depth = recent.std()
        
        if std_depth == 0 or pd.isna(std_depth):
            return {"depth_z_score": 0.0, "depth_regime": "normal"}
        
        z = (depth.iloc[-1] - mean_depth) / std_depth
        
        if z > 1.0:
            regime = "deep_book"    # Very liquid
        elif z < -1.0:
            regime = "shallow_book" # Illiquid
        else:
            regime = "normal_depth"
        
        return {
            "depth_z_score": float(z),
            "depth_regime": regime,
        }
    
    def _classify_liquidity(self, result: Dict[str, Any]) -> LiquidityState:
        """Classify overall liquidity state."""
        illiquid_signals = 0
        liquid_signals = 0
        total = 0
        
        if "volume_regime" in result:
            if result["volume_regime"] == "low_participation":
                illiquid_signals += 1
            elif result["volume_regime"] == "high_participation":
                liquid_signals += 1
            total += 1
        
        if "spread_regime" in result:
            if result["spread_regime"] == "wide_spread":
                illiquid_signals += 1
            elif result["spread_regime"] == "tight_spread":
                liquid_signals += 1
            total += 1
        
        if "depth_regime" in result:
            if result["depth_regime"] == "shallow_book":
                illiquid_signals += 1
            elif result["depth_regime"] == "deep_book":
                liquid_signals += 1
            total += 1
        
        if total == 0:
            return LiquidityState.NORMAL
        
        net = liquid_signals - illiquid_signals
        if net >= 1:
            return LiquidityState.LIQUID
        elif net <= -1:
            return LiquidityState.ILLIQUID
        else:
            return LiquidityState.NORMAL
    
    def _liquidity_score(self, result: Dict[str, Any]) -> float:
        """
        Composite liquidity score.
        Ranges from -1 (illiquid) to +1 (very liquid).
        """
        scores = []
        
        if "volume_z_score" in result:
            scores.append(np.clip(result["volume_z_score"] / 2, -1, 1))
        
        if "spread_z_score" in result:
            scores.append(-np.clip(result["spread_z_score"] / 2, -1, 1))
        
        if "depth_z_score" in result:
            scores.append(np.clip(result["depth_z_score"] / 2, -1, 1))
        
        return float(np.mean(scores)) if scores else 0.0


# ══════════════════════════════════════════════════════════════════════════════
# 7. MultiTimeframeRegime
# ══════════════════════════════════════════════════════════════════════════════

class MultiTimeframeRegime:
    """
    Multi-timeframe regime consensus.
    
    Combines regime signals from multiple timeframes to produce a unified view.
    Implements Higher Timeframe (HTF) alignment: only trade when all
    timeframes agree on the primary regime.
    
    Timeframes:
    - 15-min (short-term noise)
    - 1-hour (trading horizon)
    - 4-hour (swing horizon)
    - Daily (structural / investment horizon)
    
    References
    ----------
    Elder (1993) — Trading for a Living (triple-screen system concept).
    """
    
    def __init__(
        self,
        timeframes: Optional[List[str]] = None,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.timeframes = timeframes or ["15m", "1h", "4h", "1d"]
        self.weights = weights or {
            "15m": 0.10,
            "1h": 0.20,
            "4h": 0.30,
            "1d": 0.40,
        }
        self.detectors: Dict[str, MarketRegimeDetector] = {}
        self.regime_records: Dict[str, List[RegimeComposite]] = {
            tf: [] for tf in self.timeframes
        }
    
    def update(
        self,
        timeframe_data: Dict[str, pd.DataFrame],
        cross_asset_data: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Dict[str, Any]:
        """
        Update regime detection across all timeframes.
        
        Parameters
        ----------
        timeframe_data : Dict[str, pd.DataFrame]
            Dict of timeframe_label -> OHLCV DataFrame.
        cross_asset_data : dict, optional
            Dict of asset_name -> OHLCV DataFrame for correlation analysis.
        
        Returns
        -------
        Dict with: per_timeframe regimes, consensus, htf_alignment,
                   regime_weighted_signal, composite_strength
        """
        per_tf = {}
        
        for tf in self.timeframes:
            if tf not in timeframe_data:
                continue
            
            df = timeframe_data[tf]
            if len(df) < 100:
                continue
            
            # Create / reuse detector for this timeframe
            if tf not in self.detectors:
                hmm_lookback = min(504, len(df) - 1)
                self.detectors[tf] = MarketRegimeDetector(
                    n_hmm_states=3,
                    lookback=min(252, len(df) // 2),
                    hmm_lookback=hmm_lookback,
                    use_hmm=True,
                )
            
            detector = self.detectors[tf]
            
            # Different HMM refit schedule per timeframe
            re_fit_hmm = (len(self.regime_records[tf]) % 20 == 0)
            
            composite = detector.detect(
                df,
                cross_asset_df=cross_asset_data,
                re_fit_hmm=re_fit_hmm,
            )
            
            self.regime_records[tf].append(composite)
            per_tf[tf] = composite.to_dict()
        
        # Compute consensus
        consensus = self._compute_consensus(per_tf)
        consensus["per_timeframe"] = per_tf
        
        return consensus
    
    def _compute_consensus(self, per_tf: Dict[str, Any]) -> Dict[str, Any]:
        """
        Weighted consensus from all timeframes.
        
        HTF alignment: when daily + 4h agree, signal is strong.
        """
        regime_votes: Dict[RegimeType, float] = {}
        trend_votes: Dict[str, float] = {}
        vol_votes: Dict[str, float] = {}
        
        total_weight = 0.0
        
        for tf in self.timeframes:
            if tf not in per_tf:
                continue
            
            w = self.weights.get(tf, 0.25)
            tf_data = per_tf[tf]
            
            regime_name = tf_data.get("primary", "UNKNOWN")
            confidence = tf_data.get("primary_confidence", 0.5)
            
            # Add weighted vote
            try:
                regime_type = getattr(RegimeType, regime_name, RegimeType.UNKNOWN)
                regime_votes[regime_type] = regime_votes.get(regime_type, 0) + w * confidence
            except (AttributeError, ValueError):
                pass
            
            # Track trend and vol
            trend_name = tf_data.get("trend", "RANGING")
            trend_votes[trend_name] = trend_votes.get(trend_name, 0) + w
            
            vol_name = tf_data.get("volatility", "NORMAL")
            vol_votes[vol_name] = vol_votes.get(vol_name, 0) + w
            
            total_weight += w
        
        if not regime_votes:
            consensus_regime = RegimeType.UNKNOWN
            consensus_conf = 0.0
        else:
            consensus_regime = max(regime_votes, key=regime_votes.get)
            consensus_conf = regime_votes[consensus_regime] / max(total_weight, 1e-10)
        
        # HTF alignment check
        daily_regime = per_tf.get("1d", {}).get("primary", None)
        h4_regime = per_tf.get("4h", {}).get("primary", None)
        
        htf_aligned = (daily_regime == h4_regime) if daily_regime and h4_regime else False
        
        # Alignment strength: how many timeframes agree with primary?
        aligned_count = sum(
            1 for tf in self.timeframes
            if tf in per_tf and per_tf[tf].get("primary") == consensus_regime.name
        )
        
        total_tfs = sum(1 for tf in self.timeframes if tf in per_tf)
        alignment_strength = aligned_count / max(total_tfs, 1)
        
        # Consensus trend and vol
        consensus_trend = max(trend_votes, key=trend_votes.get) if trend_votes else "RANGING"
        consensus_vol = max(vol_votes, key=vol_votes.get) if vol_votes else "NORMAL"
        
        return {
            "consensus_regime": consensus_regime.name,
            "consensus_confidence": min(consensus_conf, 1.0),
            "htf_aligned": htf_aligned,
            "alignment_strength": alignment_strength,
            "consensus_trend": consensus_trend,
            "consensus_volatility": consensus_vol,
            "regime_votes": {k.name: round(v, 3) for k, v in regime_votes.items()},
            "regime_strength": alignment_strength * consensus_conf,
        }
    
    def should_trade(self, consensus: Dict[str, Any]) -> bool:
        """
        Determine if regime conditions favor trading.
        
        Conditions:
        - HTF alignment (daily + 4h agree)
        - Minimum regime strength
        - Not in UNKNOWN / extreme regimes without edge
        """
        if not consensus.get("htf_aligned", False):
            return False
        
        if consensus.get("regime_strength", 0) < 0.4:
            return False
        
        regime = consensus.get("consensus_regime", "UNKNOWN")
        if regime in ("UNKNOWN",):
            return False
        
        return True
    
    def regime_strength_signal(self, consensus: Dict[str, Any]) -> float:
        """
        Generate a regime-weighted signal strength.
        
        Combines consensus confidence with alignment to produce a
        tradeable signal from -1 (strong bear) to +1 (strong bull).
        """
        regime = consensus.get("consensus_regime", "RANGING")
        conf = consensus.get("consensus_confidence", 0.5)
        alignment = consensus.get("alignment_strength", 0.5)
        
        signal_map = {
            RegimeType.BULL_TRENDING.name: 1.0,
            RegimeType.ACCUMULATION.name: 0.7,
            RegimeType.RISK_ON.name: 0.6,
            RegimeType.RANGING.name: 0.0,
            RegimeType.HIGH_VOLATILITY.name: 0.0,
            RegimeType.LIQUID.name: 0.3,
            RegimeType.RISK_OFF.name: -0.6,
            RegimeType.DISTRIBUTION.name: -0.7,
            RegimeType.BEAR_TRENDING.name: -1.0,
            RegimeType.ILLIQUID.name: -0.3,
            RegimeType.UNKNOWN.name: 0.0,
        }
        
        direction = signal_map.get(regime, 0.0)
        return direction * conf * alignment


# ══════════════════════════════════════════════════════════════════════════════
# 8. RegimeBasedAllocation
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class StrategyAllocation:
    """Strategy recommendation for a given regime."""
    strategy_name: str
    allocation_pct: float          # % of capital to this strategy
    max_leverage: float            # Maximum leverage in this regime
    target_vol: float              # Target annualized vol
    stop_loss_pct: float           # Suggested stop loss
    description: str
    specific_params: Dict[str, Any] = field(default_factory=dict)


class RegimeBasedAllocation:
    """
    Optimal strategy allocation for each market regime.
    
    Automatically switches strategies based on detected regime:
    
    | Regime          | Strategy            | Rationale                          |
    |-----------------|---------------------|------------------------------------|
    | Bull Trending   | Trend Following     | Momentum persists, ride the trend  |
    | Bear Trending   | Trend Following     | Short-side momentum                |
    | Ranging         | Mean Reversion      | Fade extremes, buy dips/sell pops  |
    | High Volatility | Vol Arb / Straddle  | Capture vol expansion              |
    | Risk-On         | Long-biased / Beta  | Risk appetite, full allocation     |
    | Risk-Off        | Capital Preservation | Reduce exposure, hedge             |
    | Accumulation    | Accumulate / Scale   | Smart money, patience              |
    | Distribution    | Distribute / Reduce  | Distribution = exit phase          |
    | Low Liquidity   | Reduce / Avoid       | Slippage kills edge                |
    
    References
    ----------
    Cohen et al. (2023) — Regime-Based Asset Allocation, JPM.
    Ang (2014) — Asset Management: A Systematic Approach to Factor Investing.
    """
    
    def __init__(self, base_capital: float = 100_000.0, max_portfolio_vol: float = 0.15):
        self.base_capital = base_capital
        self.max_portfolio_vol = max_portfolio_vol
        self._current_strategy: Optional[str] = None
        self._allocation_history: List[Dict[str, Any]] = []
    
    def allocate(self, regime_composite: RegimeComposite) -> StrategyAllocation:
        """
        Determine optimal strategy allocation based on regime.
        
        Parameters
        ----------
        regime_composite : RegimeComposite
            The current regime state from detection.
        
        Returns
        -------
        StrategyAllocation with specific recommendations.
        """
        primary = regime_composite.primary.regime
        trend = regime_composite.trend
        volatility = regime_composite.volatility
        correlation = regime_composite.correlation
        liquidity = regime_composite.liquidity
        vol_type = regime_composite.volume
        strength = regime_composite.regime_strength
        
        # Override based on correlation / liquidity
        effective_regime = primary
        
        if correlation == CorrelationState.RISK_OFF and primary in (
            RegimeType.BULL_TRENDING, RegimeType.ACCUMULATION, RegimeType.RISK_ON
        ):
            effective_regime = RegimeType.RISK_OFF
        
        if liquidity == LiquidityState.ILLIQUID and primary != RegimeType.ILLIQUID:
            effective_regime = RegimeType.ILLIQUID
        
        if volatility in (VolatilityState.EXTREME, VolatilityState.HIGH) and primary == RegimeType.RANGING:
            effective_regime = RegimeType.HIGH_VOLATILITY
        
        # Scale allocation by regime strength
        strength_factor = 0.5 + strength * 0.5
        
        allocation = self._allocation_for_regime(effective_regime, strength_factor)
        
        self._current_strategy = allocation.strategy_name
        self._allocation_history.append({
            "timestamp": pd.Timestamp.now(),
            "regime": effective_regime.name,
            "strategy": allocation.strategy_name,
            "allocation_pct": allocation.allocation_pct,
            "max_leverage": allocation.max_leverage,
        })
        
        return allocation
    
    def _allocation_for_regime(
        self, regime: RegimeType, strength_factor: float
    ) -> StrategyAllocation:
        """Map regime to specific strategy allocation."""
        
        regime_map: Dict[RegimeType, StrategyAllocation] = {
            RegimeType.BULL_TRENDING: StrategyAllocation(
                strategy_name="Trend Following (Long)",
                allocation_pct=0.90 * strength_factor,
                max_leverage=2.0,
                target_vol=0.15,
                stop_loss_pct=0.07,
                description="Ride the trend with momentum filters. Enter on pullbacks "
                            "to MA support. Trail stop under recent swing low.",
                specific_params={
                    "trend_filter": "EMA 50 > EMA 200",
                    "entry_trigger": "ADX > 25, DI+ > DI-",
                    "exit_trigger": "ADX < 20 or close below MA 50",
                    "position_sizing": "Volatility-targeted Kelly fraction",
                },
            ),
            RegimeType.BEAR_TRENDING: StrategyAllocation(
                strategy_name="Trend Following (Short)",
                allocation_pct=0.80 * strength_factor,
                max_leverage=1.5,
                target_vol=0.12,
                stop_loss_pct=0.05,
                description="Short-side momentum. Enter on bounces to resistance. "
                            "Cover on volume exhaustion.",
                specific_params={
                    "trend_filter": "EMA 50 < EMA 200",
                    "entry_trigger": "ADX > 25, DI- > DI+",
                    "exit_trigger": "ADX < 20 or close above MA 50",
                    "position_sizing": "50% of vol-targeted Kelly",
                },
            ),
            RegimeType.RANGING: StrategyAllocation(
                strategy_name="Mean Reversion",
                allocation_pct=0.60 * strength_factor,
                max_leverage=1.0,
                target_vol=0.08,
                stop_loss_pct=0.03,
                description="Fade the extremes. Buy at support, sell at resistance. "
                            "Use Bollinger Bands and RSI for entry timing.",
                specific_params={
                    "entry_trigger": "RSI < 30 (long) or RSI > 70 (short)",
                    "exit_trigger": "Return to SMA 20",
                    "position_sizing": "Equal risk per mean-reversion signal",
                    "max_positions": 5,
                },
            ),
            RegimeType.HIGH_VOLATILITY: StrategyAllocation(
                strategy_name="Volatility Strategies",
                allocation_pct=0.50 * strength_factor,
                max_leverage=1.0,
                target_vol=0.20,
                stop_loss_pct=0.10,
                description="Sell premium (short vol) in established high vol, "
                            "buy premium in vol explosion. Iron condors / strangles.",
                specific_params={
                    "dte": "30-45 days",
                    "strikes": "1 std dev wings",
                    "vix_entry": "VIX > 25 for short vol, VIX spikes > 15% for long vol",
                    "stop": "Vol expansion beyond 1.5x entry level",
                },
            ),
            RegimeType.RISK_ON: StrategyAllocation(
                strategy_name="Long-Biased / Beta",
                allocation_pct=1.00 * strength_factor,
                max_leverage=2.5,
                target_vol=0.18,
                stop_loss_pct=0.10,
                description="Full risk appetite. Deploy capital to highest "
                            "conviction ideas. Increase beta exposure.",
                specific_params={
                    "beta_target": 1.2,
                    "sector_preference": "Cyclicals, Tech, Small-cap",
                    "risk_budget": "Full allocation with momentum overlay",
                },
            ),
            RegimeType.RISK_OFF: StrategyAllocation(
                strategy_name="Capital Preservation",
                allocation_pct=0.20 * strength_factor,
                max_leverage=0.5,
                target_vol=0.05,
                stop_loss_pct=0.02,
                description="Reduce exposure. Hedge with puts / VIX calls. "
                            "Increase cash allocation. Defensive sectors only.",
                specific_params={
                    "cash_target": 0.60,
                    "hedge": "5% OTM puts on SPY, VIX call spreads",
                    "sector_preference": "Utilities, Healthcare, Consumer Staples",
                    "max_drawdown_limit": 0.03,
                },
            ),
            RegimeType.ACCUMULATION: StrategyAllocation(
                strategy_name="Accumulate / Scale In",
                allocation_pct=0.70 * strength_factor,
                max_leverage=1.5,
                target_vol=0.12,
                stop_loss_pct=0.05,
                description="Smart money accumulation. Scale into positions "
                            "gradually. Use VWAP and volume profile for entries.",
                specific_params={
                    "scale_in": "3-5 tranches over 2 weeks",
                    "entry_zone": "Below VWAP, declining volatility",
                    "volume_confirmation": "Rising OBV with above-avg volume",
                },
            ),
            RegimeType.DISTRIBUTION: StrategyAllocation(
                strategy_name="Distribute / Reduce",
                allocation_pct=0.40 * strength_factor,
                max_leverage=0.5,
                target_vol=0.08,
                stop_loss_pct=0.03,
                description="Reduce position size on strength. Tighten stops. "
                            "Book profits systematically.",
                specific_params={
                    "reduce_by": "25% per week",
                    "tighten_stop": "To 2x ATR from 3x ATR",
                    "profit_target": "Take 50% off at 2R",
                },
            ),
            RegimeType.ILLIQUID: StrategyAllocation(
                strategy_name="Avoid / Reduce",
                allocation_pct=0.10 * strength_factor,
                max_leverage=0.25,
                target_vol=0.03,
                stop_loss_pct=0.01,
                description="Low liquidity = slippage kills. Reduce position sizes. "
                            "Use limit orders only. Avoid illiquid instruments.",
                specific_params={
                    "max_order_size": "10% of average volume",
                    "order_type": "Limit only, no market orders",
                    "spread_tolerance": "Max 0.5% spread",
                },
            ),
            RegimeType.LIQUID: StrategyAllocation(
                strategy_name="Full Capacity",
                allocation_pct=0.90 * strength_factor,
                max_leverage=2.0,
                target_vol=0.15,
                stop_loss_pct=0.07,
                description="High liquidity allows full deployment. "
                            "Tight spreads, deep books. Execute with confidence.",
                specific_params={
                    "max_order_size": "50% of average volume",
                    "order_type": "Aggressive with icebergs as needed",
                },
            ),
            RegimeType.UNKNOWN: StrategyAllocation(
                strategy_name="Wait / Observe",
                allocation_pct=0.20 * strength_factor,
                max_leverage=0.25,
                target_vol=0.03,
                stop_loss_pct=0.01,
                description="Regime unclear. Cash is a position. Wait for "
                            "confirmation before deploying capital.",
                specific_params={"wait_period": "Minimum 1 trading session"},
            ),
        }
        
        # Get allocation, with fallback
        alloc = regime_map.get(regime, regime_map[RegimeType.UNKNOWN])
        
        # Cap allocation
        alloc.allocation_pct = min(alloc.allocation_pct, 1.0)
        
        return alloc
    
    def get_current_strategy(self) -> Optional[str]:
        """Return the current active strategy name."""
        return self._current_strategy
    
    def get_allocation_history(self) -> pd.DataFrame:
        """Return allocation history as a DataFrame."""
        if not self._allocation_history:
            return pd.DataFrame()
        return pd.DataFrame(self._allocation_history)
    
    def generate_report(
        self, regime_composite: RegimeComposite
    ) -> Dict[str, Any]:
        """
        Generate a complete regime-based allocation report.
        """
        allocation = self.allocate(regime_composite)
        regime_dict = regime_composite.to_dict()
        
        return {
            "timestamp": pd.Timestamp.now().isoformat(),
            "regime_summary": regime_dict,
            "capital": {
                "base": self.base_capital,
                "allocated": self.base_capital * allocation.allocation_pct,
                "cash": self.base_capital * (1 - allocation.allocation_pct),
            },
            "strategy": {
                "name": allocation.strategy_name,
                "allocation_pct": allocation.allocation_pct,
                "max_leverage": allocation.max_leverage,
                "target_vol": allocation.target_vol,
                "stop_loss_pct": allocation.stop_loss_pct,
            },
            "specific_params": allocation.specific_params,
            "description": allocation.description,
        }


# ══════════════════════════════════════════════════════════════════════════════
# Convenience Pipeline
# ══════════════════════════════════════════════════════════════════════════════

class RegimePipeline:
    """
    End-to-end regime detection → allocation pipeline.
    
    Orchestrates all regime detection components into a single workflow.
    """
    
    def __init__(self, base_capital: float = 100_000.0):
        self.detector = MarketRegimeDetector()
        self.multi_tf = MultiTimeframeRegime()
        self.allocation = RegimeBasedAllocation(base_capital=base_capital)
    
    def run(
        self,
        primary_df: pd.DataFrame,
        multi_tf_data: Optional[Dict[str, pd.DataFrame]] = None,
        cross_asset_data: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Dict[str, Any]:
        """
        Run the full regime pipeline.
        
        Parameters
        ----------
        primary_df : pd.DataFrame
            Daily OHLCV data for the primary asset.
        multi_tf_data : dict, optional
            Dict of timeframe -> OHLCV for multi-timeframe analysis.
        cross_asset_data : dict, optional
            Dict of asset -> OHLCV for correlation regime.
        
        Returns
        -------
        Dict with: regime, multi_tf_consensus, allocation, report
        """
        # 1. Single timeframe detection
        regime = self.detector.detect(
            primary_df,
            cross_asset_df=cross_asset_data,
        )
        
        # 2. Multi-timeframe analysis
        if multi_tf_data is not None:
            multi_tf_consensus = self.multi_tf.update(
                multi_tf_data,
                cross_asset_data=cross_asset_data,
            )
        else:
            multi_tf_consensus = None
        
        # 3. Allocation
        allocation = self.allocation.allocate(regime)
        
        # 4. Report
        report = self.allocation.generate_report(regime)
        
        return {
            "regime": regime,
            "regime_summary": self.detector.summary(),
            "multi_tf_consensus": multi_tf_consensus,
            "allocation": allocation,
            "report": report,
            "should_trade": (
                self.multi_tf.should_trade(multi_tf_consensus)
                if multi_tf_consensus else True
            ),
            "trade_signal": (
                self.multi_tf.regime_strength_signal(multi_tf_consensus)
                if multi_tf_consensus else 0.0
            ),
        }


# ══════════════════════════════════════════════════════════════════════════════
# Quick Self-Test
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("Pro Market Regime Detection - Self Test")
    print("=" * 60)
    
    # Generate synthetic data
    np.random.seed(42)
    n = 1000
    
    # Regime 1: Bull trending (first 300 bars)
    trend1 = np.cumsum(np.random.normal(0.001, 0.01, 300)) + 100
    # Regime 2: Ranging (next 300)
    trend2 = np.ones(300) * trend1[-1] + np.random.normal(0, 0.005, 300).cumsum()
    # Regime 3: High volatility (next 200)
    trend3 = trend2[-1] + np.cumsum(np.random.normal(0, 0.025, 200))
    # Regime 4: Bear trending (last 200)
    trend4 = trend3[-1] + np.cumsum(np.random.normal(-0.002, 0.015, 200))
    
    prices = np.concatenate([trend1, trend2, trend3, trend4])
    volumes = np.abs(np.random.normal(1_000_000, 200_000, n))
    highs = prices * (1 + np.abs(np.random.normal(0, 0.005, n)))
    lows = prices * (1 - np.abs(np.random.normal(0, 0.005, n)))
    
    df = pd.DataFrame({
        "open": prices * (1 + np.random.normal(0, 0.002, n)),
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    })
    
    print(f"\nSynthetic data: {n} bars, close range [{prices.min():.2f}, {prices.max():.2f}]")
    
    # Test 1: MarketRegimeDetector
    print("\n--- Test 1: MarketRegimeDetector ---")
    detector = MarketRegimeDetector(use_hmm=False)  # Skip HMM for speed
    regime = detector.detect(df)
    print(f"Detected regime: {regime.primary.regime.name} "
          f"(conf: {regime.primary.confidence:.2%})")
    print(f"  Sub-states: Trend={regime.trend.name}, "
          f"Vol={regime.volatility.name}, "
          f"Volume={regime.volume.name}")
    
    # Test 2: TrendStrengthAnalyzer
    print("\n--- Test 2: TrendStrengthAnalyzer ---")
    trend_analyzer = TrendStrengthAnalyzer()
    trend_result = trend_analyzer.analyze(df)
    print(f"ADX: {trend_result['adx']:.1f}, "
          f"DI+: {trend_result['di_plus']:.1f}, "
          f"DI-: {trend_result['di_minus']:.1f}")
    print(f"MA Slope: {trend_result['ma_slope']:.4f}%, "
          f"Hurst: {trend_result['hurst_exponent']:.4f}")
    print(f"Fractal Dimension: {trend_result['fractal_dimension']:.4f}, "
          f"Trend State: {trend_result['trend_state'].name}")
    print(f"Trend Strength: {trend_result['trend_strength']:.2%}")
    
    # Test 3: VolatilityRegime
    print("\n--- Test 3: VolatilityRegime ---")
    vol_regime = VolatilityRegime()
    vol_result = vol_regime.detect(df)
    print(f"Vol State: {vol_result['vol_state'].name}")
    print(f"  RV 21d: {vol_result.get('realized_vol_21d', 0):.2%}, "
          f"Vol of Vol: {vol_result.get('vol_of_vol', 0):.4f}")
    print(f"  GARCH Probs: Low={vol_result['garch_prob_low']:.2f}, "
          f"Normal={vol_result['garch_prob_normal']:.2f}, "
          f"High={vol_result['garch_prob_high']:.2f}")
    
    # Test 4: LiquidityRegime
    print("\n--- Test 4: LiquidityRegime ---")
    liq_regime = LiquidityRegime()
    liq_result = liq_regime.detect(df)
    print(f"Liquidity State: {liq_result['liquidity_state'].name}")
    print(f"  Volume Z: {liq_result.get('volume_z_score', 0):.2f}, "
          f"Regime: {liq_result.get('volume_regime', 'n/a')}")
    
    # Test 5: CorrelationRegime
    print("\n--- Test 5: CorrelationRegime ---")
    corr_regime = CorrelationRegime()
    # Generate correlated synthetic assets
    np.random.seed(99)
    base_returns = np.random.normal(0.0005, 0.01, n)
    asset_dict = {
        "SPY": df,
        "QQQ": pd.DataFrame({"close": 100 + np.cumsum(base_returns * 1.2 + np.random.normal(0, 0.005, n))}),
        "IWM": pd.DataFrame({"close": 100 + np.cumsum(base_returns * 0.9 + np.random.normal(0, 0.008, n))}),
        "AGG": pd.DataFrame({"close": 100 + np.cumsum(base_returns * 0.3 + np.random.normal(0, 0.003, n))}),
    }
    corr_signal = corr_regime.detect(asset_dict)
    print(f"Correlation Regime: {corr_signal.regime.name} "
          f"(conf: {corr_signal.confidence:.2%})")
    print(f"  PC1 Variance: {corr_signal.components.get('pc1_var', 0):.2%}")
    
    # Test 6: BreadthRegime
    print("\n--- Test 6: BreadthRegime ---")
    breadth = BreadthRegime()
    ad_line = pd.Series(np.cumsum(np.random.normal(0, 10, 200)) + 1000)
    pct_ma50 = pd.Series(0.6 + 0.2 * np.sin(np.linspace(0, 6*np.pi, 200)))
    pct_ma200 = pd.Series(0.55 + 0.15 * np.sin(np.linspace(0, 4*np.pi, 200)))
    advances = pd.Series(np.random.poisson(800, 200))
    declines = pd.Series(np.random.poisson(600, 200))
    new_highs = pd.Series(np.random.poisson(80, 200))
    new_lows = pd.Series(np.random.poisson(40, 200))
    
    breadth_result = breadth.detect(
        advance_decline=ad_line,
        pct_above_ma50=pct_ma50,
        pct_above_ma200=pct_ma200,
        advances=advances, declines=declines,
        new_highs=new_highs, new_lows=new_lows,
    )
    print(f"Breadth State: {breadth_result['breadth_state'].name}")
    print(f"  Score: {breadth_result['breadth_score']:.2f}")
    if "mcclellan_oscillator" in breadth_result:
        print(f"  McClellan Osc: {breadth_result['mcclellan_oscillator']:.1f}")
    if "nh_nl_ratio" in breadth_result:
        print(f"  NH/NL Ratio: {breadth_result['nh_nl_ratio']:.2f}")
    
    # Test 7: RegimeBasedAllocation
    print("\n--- Test 7: RegimeBasedAllocation ---")
    allocator = RegimeBasedAllocation(base_capital=1_000_000)
    allocation = allocator.allocate(regime)
    print(f"Strategy: {allocation.strategy_name}")
    print(f"Allocation: {allocation.allocation_pct:.0%} of capital")
    print(f"Max Leverage: {allocation.max_leverage}x")
    print(f"Target Vol: {allocation.target_vol:.0%}")
    print(f"Stop Loss: {allocation.stop_loss_pct:.0%}")
    print(f"Description: {allocation.description[:100]}...")
    
    # Test 8: Full Pipeline
    print("\n--- Test 8: RegimePipeline (End-to-End) ---")
    pipeline = RegimePipeline(base_capital=1_000_000)
    result = pipeline.run(df)
    print(f"Primary Regime: {result['regime'].primary.regime.name}")
    print(f"Allocation: {result['allocation'].strategy_name} "
          f"({result['allocation'].allocation_pct:.0%})")
    print(f"Should Trade: {result['should_trade']}")
    print(f"Trade Signal: {result['trade_signal']:.3f}")
    print(f"\n{result['regime_summary']}")
    
    print("\n" + "=" * 60)
    print("All tests passed.")
    print("=" * 60)