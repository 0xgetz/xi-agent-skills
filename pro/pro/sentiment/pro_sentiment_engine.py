
"""
pro_sentiment_engine.py — Professional-Grade Sentiment Analysis Engine

Amateurs look at price. Pros know what the crowd thinks.
Integrates NLP, on-chain metrics, social aggregation, fear-greed index,
divergence detection, and news impact analysis.

Usage:
    from pro.sentiment.pro_sentiment_engine import (
        NLPSentimentAnalyzer, FearGreedIndex, SocialAggregator,
        OnChainSentiment, SentimentDivergence, NewsImpactAnalyzer,
        SentimentEngine, SentimentSignal
    )
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

try:
    from scipy import stats as scipy_stats
except ImportError:
    scipy_stats = None

logger = logging.getLogger("SentimentEngine")

# ---------------------------------------------------------------------------
# Shared data types (mirrors what lib.gumloop_trading would provide)
# ---------------------------------------------------------------------------

@dataclass
class SentimentSignal:
    """A single sentiment reading for a target asset."""
    timestamp: datetime
    asset: str                # e.g. "BTC", "ETH", "AAPL"
    source: str               # "news", "twitter", "reddit", "onchain", "fear_greed", "composite"
    score: float              # -1.0 (extremely bearish) to +1.0 (extremely bullish)
    confidence: float         # 0.0 to 1.0
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


@dataclass
class SentimentDivergenceSignal:
    """Bullish or bearish divergence between price and sentiment."""
    timestamp: datetime
    asset: str
    div_type: str             # "bullish_divergence", "bearish_divergence", "extreme_bullish_contrarian", "extreme_bearish_contrarian"
    price_trend: str          # "up", "down", "neutral"
    sentiment_trend: str      # "up", "down", "neutral"
    score: float              # divergence magnitude
    description: str = ""


@dataclass
class NewsItem:
    """A news article with impact scoring."""
    id: str
    timestamp: datetime
    title: str
    body: str
    source: str
    url: str = ""
    category: str = "general"   # regulatory, adoption, hack, partnership, general
    entities: list = field(default_factory=list)  # [{"name": "BTC", "type": "crypto"}, ...]
    sentiment: float = 0.0
    impact_score: float = 0.0
    relevance: float = 1.0


# ===================================================================
# 1. NLPSentimentAnalyzer
# ===================================================================

class NLPSentimentAnalyzer:
    """
    NLP-based sentiment analysis using FinBERT when available,
    with a robust rule-based fallback.
    """

    def __init__(self, use_finbert: bool = False, model_name: str = "ProsusAI/finbert"):
        self.use_finbert = use_finbert
        self._model = None
        self._tokenizer = None
        self._finbert_available = False

        if use_finbert:
            self._init_finbert(model_name)

        # Entity pattern database for crypto/stocks
        self._entity_patterns: Dict[str, List[str]] = {
            "BTC": [r"\bbitcoin\b", r"\bbtc\b", r"\bBTC\b", r"\bxbt\b"],
            "ETH": [r"\bEthereum\b", r"\beth\b", r"\bETH\b"],
            "SOL": [r"\bSolana\b", r"\bsol\b", r"\bSOL\b"],
            "BNB": [r"\bBinance\b", r"\bbnb\b", r"\bBNB\b"],
            "XRP": [r"\bXRP\b", r"\bxrp\b", r"\bripple\b"],
            "ADA": [r"\bCardano\b", r"\bada\b", r"\bADA\b"],
            "DOGE": [r"\bDogecoin\b", r"\bdoge\b", r"\bDOGE\b"],
            "DOT": [r"\bPolkadot\b", r"\bDOT\b", r"\bdot\b"],
            "AVAX": [r"\bAvalanche\b", r"\bAVAX\b", r"\bavax\b"],
            "LINK": [r"\bChainlink\b", r"\bLINK\b", r"\blink\b"],
            "AAPL": [r"\bApple\b", r"\bAAPL\b", r"\baapl\b"],
            "MSFT": [r"\bMicrosoft\b", r"\bMSFT\b", r"\bmsft\b"],
            "GOOGL": [r"\bGoogle\b", r"\bGOOGL\b", r"\bAlphabet\b"],
            "AMZN": [r"\bAmazon\b", r"\bAMZN\b", r"\bamzn\b"],
            "TSLA": [r"\bTesla\b", r"\bTSLA\b", r"\btsla\b"],
            "SPY": [r"\bS&P 500\b", r"\bspy\b", r"\bSPY\b"],
        }

        # Sentiment lexicons
        self._bullish_words = {
            "bullish", "breakout", "moon", "pump", "buy", "long", "accumulate",
            "undervalued", "oversold", "support", "rally", "surge", "gain", "profit",
            "adoption", "partnership", "upgrade", "positive", "growth", "strong",
            "opportunity", "green", "hodl", "diamond hands", "ATH", "all-time high",
            "outperform", "beat", "raise", "upgrade", "bull run", "flippening",
            "institutional", "mainstream", "regulation", "ETF", "approval",
        }
        self._bearish_words = {
            "bearish", "breakdown", "dump", "crash", "sell", "short", "distribute",
            "overvalued", "overbought", "resistance", "decline", "plunge", "loss", "drop",
            "hack", "exploit", "fraud", "scam", "negative", "weak", "fear",
            "red", "panic", "sell-off", "correction", "bear market", "capitulation",
            "underperform", "miss", "lower", "downgrade", "bankrupt", "liquidation",
            "unregulated", "ban", "crackdown", "restrict",
        }

        # Category classifiers (regex patterns)
        self._category_patterns: Dict[str, List[str]] = {
            "regulatory": [
                r"\bSEC\b", r"\bregulation\b", r"\bregulatory\b", r"\bcrackdown\b",
                r"\bben?[ck]\b", r"\bcompliance\b", r"\blaw\b", r"\bcongress\b",
                r"\bcourt\b", r"\blawsuit\b", r"\blitigation\b",
            ],
            "adoption": [
                r"\badopt", r"\baccept", r"\bintegrat", r"\bpayment\b", r"\bmerchant\b",
                r"\bmainstream\b", r"\binstitutional\b", r"\blaunch\b", r"\brollout\b",
            ],
            "hack": [
                r"\bhack", r"\bexploit\b", r"\bbreach\b", r"\btheft\b", r"\bstolen\b",
                r"\bransom", r"\battack\b", r"\bcompromis", r"\bdrain\b",
            ],
            "partnership": [
                r"\bpartnership\b", r"\bpartner\b", r"\balliance\b", r"\bcollaborat",
                r"\bjoin[ts]\b", r"\bintegrat", r"\bagreement\b",
            ],
        }

    def _init_finbert(self, model_name: str) -> None:
        """Attempt to load FinBERT. Falls back gracefully."""
        try:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            self._tokenizer = AutoTokenizer.from_pretrained(model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(model_name)
            self._finbert_available = True
            logger.info(f"FinBERT loaded: {model_name}")
        except Exception as e:
            logger.warning(f"FinBERT unavailable ({e}), using rule-based fallback")
            self._finbert_available = False

    def analyze_text(self, text: str) -> Tuple[float, float]:
        """
        Analyze a single text.
        Returns (sentiment_score, confidence).
        score: -1.0 (bearish) to +1.0 (bullish)
        """
        if self._finbert_available and self._model is not None:
            return self._analyze_finbert(text)
        return self._analyze_rule_based(text)

    def _analyze_finbert(self, text: str) -> Tuple[float, float]:
        """FinBERT inference."""
        try:
            import torch
            inputs = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
            with torch.no_grad():
                outputs = self._model(**inputs)
                probs = torch.nn.functional.softmax(outputs.logits, dim=-1)
                # FinBERT: 0=negative, 1=neutral, 2=positive
                neg, neu, pos = probs[0].tolist()
                score = pos - neg
                confidence = 1.0 - neu
                return score, confidence
        except Exception as e:
            logger.warning(f"FinBERT inference failed ({e}), falling back")
            return self._analyze_rule_based(text)

    def _analyze_rule_based(self, text: str) -> Tuple[float, float]:
        """Lexicon-based sentiment analysis."""
        text_lower = text.lower()
        words = re.findall(r'\b[a-zA-Z]+\b', text_lower)

        bullish_count = sum(1 for w in self._bullish_words if w in text_lower)
        bearish_count = sum(1 for w in self._bearish_words if w in text_lower)

        # Also check bigrams
        for bw in self._bullish_words:
            if " " in bw and bw in text_lower:
                bullish_count += 1
        for bw in self._bearish_words:
            if " " in bw and bw in text_lower:
                bearish_count += 1

        total_words = len(words) if words else 1
        total_sentiment_words = bullish_count + bearish_count

        if total_sentiment_words == 0:
            return 0.0, 0.0

        score = (bullish_count - bearish_count) / total_sentiment_words
        score = max(-1.0, min(1.0, score))
        confidence = total_sentiment_words / max(total_words, 10)  # normalized by text length
        confidence = min(1.0, confidence * 5)  # scale up

        return score, confidence

    def extract_entities(self, text: str) -> List[Dict[str, Any]]:
        """Extract mentioned entities (coins/stocks) from text."""
        found = []
        for entity, patterns in self._entity_patterns.items():
            for pat in patterns:
                if re.search(pat, text, re.IGNORECASE):
                    # Count mentions
                    count = len(re.findall(pat, text, re.IGNORECASE))
                    found.append({"name": entity, "type": "crypto" if entity in {
                        "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "DOT", "AVAX", "LINK"
                    } else "stock", "mentions": count})
                    break
        return found

    def classify_news_category(self, text: str) -> Tuple[str, float]:
        """Classify news into category with confidence."""
        text_lower = text.lower()
        best_category = "general"
        best_score = 0.0

        for cat, patterns in self._category_patterns.items():
            score = 0.0
            for pat in patterns:
                matches = len(re.findall(pat, text_lower))
                score += matches
            if score > best_score:
                best_score = score
                best_category = cat

        confidence = min(1.0, best_score / 5.0)
        return best_category, confidence

    def analyze_news(self, news_items: List[NewsItem]) -> List[SentimentSignal]:
        """Analyze a batch of news items."""
        signals = []
        for item in news_items:
            if not item.body and not item.title:
                continue
            full_text = f"{item.title}. {item.body}" if item.title and item.body else (item.title or item.body or "")

            # Sentiment
            score, confidence = self.analyze_text(full_text)

            # Category
            category, cat_conf = self.classify_news_category(full_text)

            # Entities
            entities = self.extract_entities(full_text)

            # Entity-level signals
            if entities:
                for ent in entities:
                    signals.append(SentimentSignal(
                        timestamp=item.timestamp,
                        asset=ent["name"],
                        source="news",
                        score=score,
                        confidence=confidence * 0.8 + 0.2 * cat_conf,
                        details={
                            "news_id": item.id,
                            "title": item.title[:100],
                            "category": category,
                            "source": item.source,
                            "entity_mentions": ent["mentions"],
                        },
                    ))
            else:
                # Generic market signal
                signals.append(SentimentSignal(
                    timestamp=item.timestamp,
                    asset="MARKET",
                    source="news",
                    score=score,
                    confidence=confidence,
                    details={
                        "news_id": item.id,
                        "title": item.title[:100],
                        "category": category,
                        "source": item.source,
                    },
                ))

        return signals

    def analyze_social_post(self, text: str, platform: str, user_followers: int = 0) -> SentimentSignal:
        """Analyze a single social media post."""
        score, confidence = self.analyze_text(text)
        entities = self.extract_entities(text)

        # Amplify confidence for high-follower accounts
        if user_followers > 10000:
            confidence = min(1.0, confidence * 1.5)

        details = {"platform": platform, "text_snippet": text[:80]}

        if not entities:
            return SentimentSignal(
                timestamp=datetime.now(timezone.utc),
                asset="MARKET", source=platform, score=score,
                confidence=confidence, details=details,
            )

        # Return first entity signal as primary
        ent = entities[0]
        details["entity_mentions"] = [e["name"] for e in entities]
        return SentimentSignal(
            timestamp=datetime.now(timezone.utc),
            asset=ent["name"], source=platform, score=score,
            confidence=confidence, details=details,
        )


# ===================================================================
# 2. FearGreedIndex
# ===================================================================

class FearGreedIndex:
    """
    Multi-factor Fear & Greed Index.
    Weights: Volatility 25%, Momentum 25%, Social 15%, Surveys 15%, Dominance 10%, Trends 10%.
    Output: 0 (extreme fear) to 100 (extreme greed).
    """

    WEIGHTS = {
        "volatility": 0.25,
        "market_momentum": 0.25,
        "social_media": 0.15,
        "surveys": 0.15,
        "dominance": 0.10,
        "trends": 0.10,
    }

    def __init__(self):
        self.history: List[Dict[str, Any]] = []

    def compute(
        self,
        price_data: pd.DataFrame,          # columns: ['close', 'volume'] with DatetimeIndex
        social_signals: List[SentimentSignal] = None,
        btc_dominance: float = 45.0,       # BTC dominance percentage
        survey_score: float = 50.0,         # survey-based sentiment (0-100)
        trend_data: Optional[pd.Series] = None,
    ) -> Dict[str, Any]:
        """
        Compute the Fear & Greed Index.
        Returns dict with factor breakdown and final index.
        """
        now = datetime.now(timezone.utc)
        social_signals = social_signals or []

        # 1. Volatility factor (recent 30-day vol vs 90-day vol)
        vol_factor = self._compute_volatility_factor(price_data)

        # 2. Market momentum factor
        momentum_factor = self._compute_momentum_factor(price_data)

        # 3. Social media factor
        social_factor = self._compute_social_factor(social_signals)

        # 4. Dominance factor
        dominance_factor = self._compute_dominance_factor(btc_dominance)

        # 5. Survey factor
        survey_factor = max(0.0, min(100.0, survey_score))

        # 6. Trends factor
        trends_factor = self._compute_trends_factor(trend_data)

        factors = {
            "volatility": vol_factor,
            "market_momentum": momentum_factor,
            "social_media": social_factor,
            "surveys": survey_factor,
            "dominance": dominance_factor,
            "trends": trends_factor,
        }

        index = sum(factors[k] * self.WEIGHTS[k] for k in self.WEIGHTS)

        classification = self._classify(index)

        result = {
            "timestamp": now.isoformat(),
            "index": round(index, 2),
            "classification": classification,
            "factors": {k: round(v, 2) for k, v in factors.items()},
            "weights": self.WEIGHTS,
        }

        self.history.append(result)
        return result

    def _compute_volatility_factor(self, price_data: pd.DataFrame) -> float:
        """
        High volatility = fear (low index).
        Compare recent 30d to 90d vol.
        """
        if price_data is None or len(price_data) < 30:
            return 50.0

        closes = price_data["close"].dropna()
        returns = closes.pct_change().dropna()

        if len(returns) < 30:
            return 50.0

        vol_30 = returns.tail(30).std()
        vol_90 = returns.tail(90).std() if len(returns) >= 90 else vol_30

        if vol_90 == 0:
            return 50.0

        vol_ratio = vol_30 / vol_90
        # Lower ratio = lower vol = less fear. Scale to 0-100.
        # Normal vol ratio ~1.0 => 50. Ratio of 2.0 => 0 (extreme fear).
        # Ratio of 0.5 => 100 (extreme greed).
        vol_factor = 50.0 - (vol_ratio - 1.0) * 50.0
        return max(0.0, min(100.0, vol_factor))

    def _compute_momentum_factor(self, price_data: pd.DataFrame) -> float:
        """Compare current price to SMA(30) and SMA(90)."""
        if price_data is None or len(price_data) < 30:
            return 50.0

        closes = price_data["close"].dropna()
        current = closes.iloc[-1]

        sma_30 = closes.tail(30).mean()
        sma_90 = closes.tail(90).mean() if len(closes) >= 90 else sma_30

        # How far above/below SMAs
        pct_above_30 = (current / sma_30 - 1.0) * 100.0
        pct_above_90 = (current / sma_90 - 1.0) * 100.0

        avg_pct = (pct_above_30 + pct_above_90) / 2.0

        # -20% (extreme fear) to +20% (extreme greed)
        momentum = 50.0 + avg_pct * 2.5
        return max(0.0, min(100.0, momentum))

    def _compute_social_factor(self, signals: List[SentimentSignal]) -> float:
        """Aggregate social signals into a 0-100 score."""
        if not signals:
            return 50.0

        # Weight by confidence
        total_weight = 0.0
        weighted_sum = 0.0
        for s in signals:
            w = s.confidence
            # Score -1..1 -> 0..100
            weighted_sum += ((s.score + 1.0) / 2.0 * 100.0) * w
            total_weight += w

        if total_weight == 0:
            return 50.0

        return max(0.0, min(100.0, weighted_sum / total_weight))

    def _compute_dominance_factor(self, btc_dominance: float) -> float:
        """
        High BTC dominance often means fear (people fleeing alts to BTC safety).
        Low dominance means risk-on (greed).
        """
        # Typically ranges 35% - 65%
        # 65%+ dominance = extreme fear (0)
        # 35%- = extreme greed (100)
        dominance = 100.0 - (btc_dominance - 35.0) / 30.0 * 100.0
        return max(0.0, min(100.0, dominance))

    def _compute_trends_factor(self, trend_data: Optional[pd.Series]) -> float:
        """Google Trends / search volume factor."""
        if trend_data is None or len(trend_data) < 2:
            return 50.0

        # Compare recent to historical average
        recent = trend_data.tail(7).mean()
        hist = trend_data.mean()

        if hist == 0:
            return 50.0

        ratio = recent / hist
        # Ratio 2.0 = extreme greed (100), ratio 0.5 = extreme fear (0)
        trends = 50.0 + (ratio - 1.0) * 50.0
        return max(0.0, min(100.0, trends))

    @staticmethod
    def _classify(index: float) -> str:
        if index >= 80:
            return "extreme_greed"
        elif index >= 60:
            return "greed"
        elif index >= 40:
            return "neutral"
        elif index >= 20:
            return "fear"
        else:
            return "extreme_fear"

    def get_signal(self) -> SentimentSignal:
        """Return current Fear & Greed as a SentimentSignal."""
        if not self.history:
            return SentimentSignal(
                timestamp=datetime.now(timezone.utc),
                asset="MARKET", source="fear_greed",
                score=0.0, confidence=0.0,
            )
        latest = self.history[-1]
        # index 0..100 -> score -1..+1
        score = (latest["index"] / 100.0) * 2.0 - 1.0
        return SentimentSignal(
            timestamp=datetime.fromisoformat(latest["timestamp"]),
            asset="MARKET",
            source="fear_greed",
            score=score,
            confidence=0.7,
            details={"index": latest["index"], "classification": latest["classification"]},
        )


# ===================================================================
# 3. SocialAggregator
# ===================================================================

class SocialAggregator:
    """
    Aggregates sentiment from social platforms.
    X/Twitter, Reddit, Telegram, Discord sentiment tracking.
    Uses mock API calls — replace with real API clients in production.
    """

    def __init__(self, api_keys: dict = None):
        self.api_keys = api_keys or {}
        self._sentiment_buffer: Dict[str, List[SentimentSignal]] = defaultdict(list)
        self._platform_stats: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

    # --- Twitter / X ---

    def track_twitter(
        self,
        query: str = "bitcoin",
        max_posts: int = 100,
        mock: bool = True,
        posts: Optional[List[str]] = None,
    ) -> List[SentimentSignal]:
        """
        Track sentiment on X/Twitter.
        mock=True: uses internal examples.
        mock=False: pass your own posts list or provide an API key for live data.
        """
        if mock:
            posts = posts or self._mock_twitter_posts(query, max_posts)

        analyzer = NLPSentimentAnalyzer()
        signals = []

        for post_text in posts:
            # Parse hypothetical follower count from mock data
            followers = 0
            if "|" in str(post_text):
                parts = str(post_text).split("|")
                post_text = parts[0]
                try:
                    followers = int(parts[1].strip())
                except (ValueError, IndexError):
                    pass

            signal = analyzer.analyze_social_post(str(post_text), "twitter", followers)
            signals.append(signal)

        self._sentiment_buffer["twitter"].extend(signals)
        self._update_platform_stats("twitter", signals)
        return signals

    def _mock_twitter_posts(self, query: str, count: int) -> List[str]:
        """Generate realistic mock tweets."""
        templates = [
            f"${query.upper()} looking incredibly strong right now. Breakout imminent. | 15000",
            f"I'm worried about ${query.upper()} short term. Resistance at key level. | 500",
            f"Just bought more ${query.upper()}. Accumulating through the dip. | 8500",
            f"{query.title()} is dead. Time to move on to better projects. | 32000",
            f"Bullish on ${query.upper()} despite FUD. Fundamentals are solid. | 1200",
            f"Major ${query.upper()} news coming. Trust me. | 200000",
            f"${query.upper()} price action looks like distribution. Be careful. | 45000",
            f"Love the ${query.upper()} ecosystem growth. Adoption is accelerating. | 7800",
            f"Shorting ${query.upper()} here. Overextended on every timeframe. | 18000",
            f"${query.upper()} support at 95k is key. If it holds, next leg up. | 2200",
            f"Just an amazing ${query.title()} development update. Team is crushing it. | 39000",
            f"Exited my ${query.upper()} position. Taking profits before the dump. | 11000",
            f"${query.upper()} will never recover from this governance mess. | 56000",
            f"Perfect time to DCA into ${query.upper()}. Don't let fear stop you. | 1500",
            f"Our firm is adding ${query.upper()} to our institutional portfolio. | 125000",
            f"${query.upper()} chart is textbook bear flag. Lower highs forming. | 28000",
            f"Community is building something special on ${query.title()}. | 6200",
            f"${query.upper()} options flow is extremely bullish this week. | 33000",
            f"Waiting for one more dip to load up on ${query.upper()}. | 9000",
            f"Something doesn't feel right about ${query.upper()}. Trust your gut. | 41000",
            f"Bought the ${query.upper()} dip near support. Let's go! | 17000",
            f"${query.upper()} to 200k is inevitable. Zoom out. | 75000",
            f"I don't trust these ${query.upper()} pumps. Looks like manipulation. | 105000",
            f"Strong buy signal on ${query.upper()} across all my indicators. | 3000",
            f"${query.upper()} network activity is at an all-time low. Concerning. | 22000",
        ]
        # Expand to meet count, rotate through templates
        result = []
        for i in range(min(count, len(templates) * 3)):
            tpl = templates[i % len(templates)]
            result.append(tpl)
        return result[:count]

    # --- Reddit ---

    def track_reddit(
        self,
        subreddits: List[str] = None,
        query: str = "bitcoin",
        max_posts: int = 50,
        mock: bool = True,
    ) -> List[SentimentSignal]:
        """Track Reddit sentiment from subreddit mentions."""
        subreddits = subreddits or ["CryptoCurrency", "Bitcoin", "CryptoMarkets"]
        if mock:
            posts = self._mock_reddit_posts(query, subreddits, max_posts)
        else:
            posts = []
            for sub in subreddits:
                posts.extend(self._fetch_reddit_posts(sub, max_posts // len(subreddits), mock=True))

        analyzer = NLPSentimentAnalyzer()
        signals = []

        for post_text in posts:
            signal = analyzer.analyze_social_post(str(post_text), "reddit", 0)
            # Boost confidence since Reddit tends to have longer-form analysis
            signal.confidence = min(1.0, signal.confidence * 1.2)
            signals.append(signal)

        self._sentiment_buffer["reddit"].extend(signals)
        self._update_platform_stats("reddit", signals)
        return signals

    def _mock_reddit_posts(self, query: str, subreddits: List[str], count: int) -> List[str]:
        """Generate realistic mock Reddit posts."""
        templates = [
            f"TA Analysis: {query.upper()} forming a massive cup and handle on weekly. Target: 150k.",
            f"ELI5: Why I think {query.upper()} is the safest investment in crypto right now.",
            f"Hot take: {query.upper()} dominance is actually bullish for alts in the long run.",
            f"Can we talk about how undervalued {query.upper()} is compared to its network effects?",
            f"Be careful everyone. {query.upper()} RSI is showing major bearish divergence on 4H.",
            f"I've been in crypto since 2017 and this {query.upper()} cycle feels different.",
            f"Unpopular opinion: {query.upper()} will not break 100k this year.",
            f"What's everyone's {query.upper()} price prediction for end of year?",
            f"Serious: Is it too late to buy {query.upper()}?",
            f"Just did a deep dive on {query.upper()}'s latest upgrade. Game changer.",
        ]
        result = []
        for i in range(min(count, len(templates) * 2)):
            tpl = templates[i % len(templates)]
            sub = subreddits[i % len(subreddits)]
            result.append(f"r/{sub}: {tpl}")
        return result[:count]

    def _fetch_reddit_posts(self, subreddit: str, limit: int, mock: bool = True) -> List[str]:
        """Placeholder for real Reddit API fetching via PRAW."""
        return self._mock_reddit_posts(f"crypto", [subreddit], limit)

    # --- Telegram ---

    def track_telegram(
        self,
        groups: List[str] = None,
        mock: bool = True,
    ) -> Dict[str, Any]:
        """Track Telegram group sentiment and activity."""
        groups = groups or ["crypto_traders", "whale_signals", "degen_alpha"]
        if mock:
            stats = self._mock_telegram_stats(groups)
        else:
            stats = {}
        return stats

    def _mock_telegram_stats(self, groups: List[str]) -> Dict[str, Dict[str, Any]]:
        """Mock Telegram group statistics."""
        base_data = {
            "crypto_traders": {"members": 45200, "messages_per_hour": 45, "ratio_bullish": 0.58},
            "whale_signals": {"members": 18200, "messages_per_hour": 12, "ratio_bullish": 0.72},
            "degen_alpha": {"members": 8900, "messages_per_hour": 89, "ratio_bullish": 0.41},
        }
        return {g: base_data.get(g, {"members": 10000, "messages_per_hour": 20, "ratio_bullish": 0.50}) for g in groups}

    # --- Discord ---

    def track_discord(
        self,
        servers: List[str] = None,
        mock: bool = True,
        member_counts: Dict[str, int] = None,
    ) -> Dict[str, Any]:
        """Track Discord server sentiment."""
        servers = servers or ["official_discord", "trading_alpha", "nft_community"]
        if mock:
            return self._mock_discord_stats(servers)
        return {}

    def _mock_discord_stats(self, servers: List[str]) -> Dict[str, Dict[str, Any]]:
        """Mock Discord server statistics."""
        base = {
            "official_discord": {"members": 145000, "growth_7d": 2.3, "message_rate_hr": 320},
            "trading_alpha": {"members": 28000, "growth_7d": -0.5, "message_rate_hr": 95},
            "nft_community": {"members": 55000, "growth_7d": -3.1, "message_rate_hr": 45},
        }
        return {s: base.get(s, {"members": 10000, "growth_7d": 0.0, "message_rate_hr": 50}) for s in servers}

    def aggregate_platform_sentiment(self, signals: List[SentimentSignal]) -> SentimentSignal:
        """Aggregate all platform signals into one composite social signal."""
        if not signals:
            return SentimentSignal(
                timestamp=datetime.now(timezone.utc),
                asset="MARKET", source="social_aggregator",
                score=0.0, confidence=0.0,
            )

        # Group by asset
        by_asset: Dict[str, List[SentimentSignal]] = defaultdict(list)
        for s in signals:
            by_asset[s.asset].append(s)

        # Composite for most mentioned asset
        main_asset = max(by_asset, key=lambda a: len(by_asset[a]))
        asset_signals = by_asset[main_asset]

        total_weight = 0.0
        weighted_score = 0.0
        for s in asset_signals:
            w = s.confidence
            # Source weighting: Twitter more weighted for fast-moving sentiment
            if s.source == "twitter":
                w *= 1.2
            elif s.source == "reddit":
                w *= 1.1
            weighted_score += s.score * w
            total_weight += w

        composite_score = weighted_score / total_weight if total_weight > 0 else 0.0
        composite_conf = min(1.0, total_weight / len(asset_signals))

        return SentimentSignal(
            timestamp=datetime.now(timezone.utc),
            asset=main_asset,
            source="social_aggregator",
            score=composite_score,
            confidence=composite_conf,
            details={
                "signal_count": len(asset_signals),
                "sources": list(set(s.source for s in asset_signals)),
                "all_assets_seen": list(by_asset.keys()),
            },
        )

    def _update_platform_stats(self, platform: str, signals: List[SentimentSignal]) -> None:
        """Update rolling platform statistics."""
        if not signals:
            return
        scores = [s.score for s in signals]
        self._platform_stats[platform]["avg_score"] = np.mean(scores)
        self._platform_stats[platform]["std_score"] = np.std(scores) if len(scores) > 1 else 0
        self._platform_stats[platform]["bullish_pct"] = sum(1 for s in scores if s > 0) / max(len(scores), 1) * 100
        self._platform_stats[platform]["count"] = len(signals)

    def get_platform_summary(self) -> Dict[str, Dict[str, float]]:
        """Get summary stats per platform."""
        return dict(self._platform_stats)


# ===================================================================
# 4. OnChainSentiment
# ===================================================================

class OnChainSentiment:
    """
    On-chain sentiment analysis.
    Uses exchange flows, whale activity, stablecoin flows, NVT, MVRV.
    """

    def __init__(self):
        self.history: Dict[str, List[float]] = defaultdict(list)

    def compute_exchange_flow_sentiment(
        self,
        inflow: float,   # BTC equivalent
        outflow: float,
        avg_inflow: float = None,
        avg_outflow: float = None,
    ) -> float:
        """
        Compute sentiment from exchange inflow/outflow.
        More outflow (withdrawal) = bullish (people HODLing).
        More inflow (deposit) = bearish (people selling).
        Returns -1 to +1.
        """
        avg_inflow = avg_inflow or inflow * 0.8
        avg_outflow = avg_outflow or outflow * 0.8

        net_flow = outflow - inflow  # positive = more leaving = bullish

        # Normalize by average flows
        avg_total = (avg_inflow + avg_outflow) / 2
        if avg_total == 0:
            return 0.0

        z_score = net_flow / avg_total  # z-score-ish: how many std's from norm
        # Clamp and scale
        sentiment = np.tanh(z_score)  # maps to (-1, 1)
        self.history["exchange_flow"].append(sentiment)
        return float(sentiment)

    def compute_whale_sentiment(
        self,
        whale_balance_change_pct: float,  # % change in whale holdings
        large_txns_buy: int,
        large_txns_sell: int,
    ) -> float:
        """
        Compute sentiment from whale activity.
        Positive balance change + more buys = bullish.
        """
        # Balance contribution (e.g., +5% -> +0.5 score)
        balance_score = np.tanh(whale_balance_change_pct / 10.0)

        # Transaction contribution
        total_txns = large_txns_buy + large_txns_sell
        if total_txns > 0:
            txn_ratio = (large_txns_buy - large_txns_sell) / total_txns
        else:
            txn_ratio = 0.0

        sentiment = 0.6 * balance_score + 0.4 * txn_ratio
        self.history["whale"].append(sentiment)
        return float(max(-1.0, min(1.0, sentiment)))

    def compute_stablecoin_flow_sentiment(
        self,
        stablecoin_inflow_btc: float,
        stablecoin_outflow_btc: float,
        exchange_stablecoin_balance_pct_change: float,
    ) -> float:
        """
        Stablecoin flows signal buying power.
        More stablecoins on exchanges = more potential buying = bullish.
        Net outflow = people moving to DeFi = also bullish.
        """
        net_stable = stablecoin_inflow_btc - stablecoin_outflow_btc  # positive = inflows to exchanges

        # Inflows to exchanges means buy-side potential
        inflow_score = np.tanh(net_stable / 10000.0)  # normalize by BTC equivalent

        # Balance change: more stablecoins on exchange = buying power building
        balance_score = np.tanh(stablecoin_balance_pct_change / 5.0)

        sentiment = 0.5 * inflow_score + 0.5 * balance_score
        self.history["stablecoin_flow"].append(sentiment)
        return float(max(-1.0, min(1.0, sentiment)))

    def compute_nvt_sentiment(self, nvt_ratio: float, historical_nvt: List[float] = None) -> float:
        """
        NVT (Network Value to Transactions) ratio.
        High NVT = overvalued (bearish). Low NVT = undervalued (bullish).
        """
        historical_nvt = historical_nvt or [25, 30, 35, 40, 45, 30, 28, 32]  # typical range ~20-80

        if not historical_nvt:
            return 0.0

        hist_mean = np.mean(historical_nvt)
        hist_std = np.std(historical_nvt) or 1.0

        z_score = (nvt_ratio - hist_mean) / hist_std
        # High z-score = high NVT = overvalued = bearish (negative sentiment)
        # Low z-score = low NVT = undervalued = bullish (positive sentiment)
        sentiment = -np.tanh(z_score / 2.0)
        self.history["nvt"].append(sentiment)
        return float(max(-1.0, min(1.0, sentiment)))

    def compute_mvrv_sentiment(self, mvrv_ratio: float) -> float:
        """
        MVRV (Market Value to Realized Value) ratio.
        MVRV > 3 = significantly overvalued (bearish).
        MVRV < 1 = undervalued (bullish).
        """
        # MVRV typically: <1 = fear, 1-2 = neutral/healthy, 2-3 = optimism, >3 = euphoria/reversal
        if mvrv_ratio <= 0:
            return 0.0

        if mvrv_ratio < 1.0:
            # Below cost basis = extreme fear (but contrarian bullish)
            sentiment = 0.5 - (1.0 - mvrv_ratio) * 2.0  # 0.5 at 1.0, -1.5 at 0... clamp
        elif mvrv_ratio < 2.0:
            # Healthy range: neutral to mildly bullish
            sentiment = (mvrv_ratio - 1.0) * 0.5  # 0 to 0.5
        elif mvrv_ratio < 3.0:
            # Optimism zone: mildly bullish to warning
            sentiment = 0.5 - (mvrv_ratio - 2.0) * 0.3  # 0.5 to 0.2
        else:
            # Euphoria zone: sell signal
            sentiment = 0.2 - (mvrv_ratio - 3.0) * 0.2  # 0.2 to negative

        self.history["mvrv"].append(sentiment)
        return float(max(-1.0, min(1.0, sentiment)))

    def aggregate_onchain_sentiment(
        self,
        exchange_flow_sent: float = 0.0,
        whale_sent: float = 0.0,
        stablecoin_sent: float = 0.0,
        nvt_sent: float = 0.0,
        mvrv_sent: float = 0.0,
    ) -> SentimentSignal:
        """Combine all on-chain factors into one composite signal."""
        weights = {
            "exchange_flow": 0.25,
            "whale": 0.25,
            "stablecoin_flow": 0.20,
            "nvt": 0.15,
            "mvrv": 0.15,
        }
        components = {
            "exchange_flow": exchange_flow_sent,
            "whale": whale_sent,
            "stablecoin_flow": stablecoin_sent,
            "nvt": nvt_sent,
            "mvrv": mvrv_sent,
        }

        composite = sum(weights[k] * components.get(k, 0.0) for k in weights)
        # Confidence based on how many components have data
        active = sum(1 for k in weights if components.get(k, 0.0) != 0.0)
        confidence = active / len(weights) * 0.7 + 0.1

        return SentimentSignal(
            timestamp=datetime.now(timezone.utc),
            asset="MARKET",
            source="onchain",
            score=float(max(-1.0, min(1.0, composite))),
            confidence=confidence,
            details={"components": components, "weights": weights},
        )


# ===================================================================
# 5. SentimentDivergence
# ===================================================================

class SentimentDivergence:
    """
    Detects divergence between price action and sentiment.
    When price and sentiment disagree, big moves often follow.
    """

    def __init__(self, lookback_periods: int = 48):
        self.lookback = lookback_periods
        self._price_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=lookback_periods * 2))
        self._sentiment_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=lookback_periods * 2))
        self._divergence_history: List[SentimentDivergenceSignal] = []

    def update(self, asset: str, price: float, sentiment: SentimentSignal) -> Optional[SentimentDivergenceSignal]:
        """Feed new price + sentiment data. Returns divergence signal if detected."""
        self._price_history[asset].append((sentiment.timestamp, price))
        self._sentiment_history[asset].append((sentiment.timestamp, sentiment.score))

        if len(self._price_history[asset]) < self.lookback:
            return None

        return self._detect_divergence(asset)

    def _detect_divergence(self, asset: str) -> Optional[SentimentDivergenceSignal]:
        """Check for price/sentiment divergence."""
        prices = np.array([p for _, p in self._price_history[asset]])
        sentiments = np.array([s for _, s in self._sentiment_history[asset]])

        if len(prices) < self.lookback or len(sentiments) < self.lookback:
            return None

        # Split into recent and old halves
        mid = len(prices) // 2
        old_prices = prices[:mid]
        recent_prices = prices[mid:]
        old_sent = sentiments[:mid]
        recent_sent = sentiments[mid:]

        # Trends: compare means of old vs recent
        price_trend = "up" if np.mean(recent_prices) > np.mean(old_prices) * 1.02 else \
                     "down" if np.mean(recent_prices) < np.mean(old_prices) * 0.98 else "neutral"

        sent_trend = "up" if np.mean(recent_sent) > np.mean(old_sent) + 0.05 else \
                    "down" if np.mean(recent_sent) < np.mean(old_sent) - 0.05 else "neutral"

        # Extreme sentiment detection
        recent_avg_sent = float(np.mean(recent_sent))
        extremes = {
            "extreme_bullish_contrarian": recent_avg_sent > 0.7,
            "extreme_bearish_contrarian": recent_avg_sent < -0.7,
        }

        # Divergence detection
        divergences = {
            "bullish_divergence": price_trend == "down" and sent_trend == "up",
            "bearish_divergence": price_trend == "up" and sent_trend == "down",
        }

        signal = None
        div_types = list(divergences.keys()) + [k for k, v in extremes.items() if v]
        if not div_types:
            return None

        now = datetime.now(timezone.utc)

        for div_type in div_types:
            # Score magnitude
            if div_type == "bullish_divergence":
                score = abs(float(np.mean(recent_prices) / np.mean(old_prices) - 1.0)) * 3 + \
                        abs(float(np.mean(recent_sent) - np.mean(old_sent))) * 2
                desc = f"Price decreasing but sentiment rising → Potential bullish reversal for {asset}"
            elif div_type == "bearish_divergence":
                score = abs(float(np.mean(recent_prices) / np.mean(old_prices) - 1.0)) * 3 + \
                        abs(float(np.mean(recent_sent) - np.mean(old_sent))) * 2
                desc = f"Price increasing but sentiment falling → Potential bearish reversal for {asset}"
            elif div_type == "extreme_bullish_contrarian":
                score = abs(recent_avg_sent) * 3
                desc = f"Extreme bullish sentiment detected ({recent_avg_sent:.2f}) → Contrarian sell signal possible"
            elif div_type == "extreme_bearish_contrarian":
                score = abs(recent_avg_sent) * 3
                desc = f"Extreme bearish sentiment detected ({recent_avg_sent:.2f}) → Contrarian buy signal possible"
            else:
                continue

            score = min(10.0, score)
            signal = SentimentDivergenceSignal(
                timestamp=now,
                asset=asset,
                div_type=div_type,
                price_trend=price_trend,
                sentiment_trend=sent_trend,
                score=score,
                description=desc,
            )
            self._divergence_history.append(signal)

        return signal

    def get_recent_divergences(self, min_score: float = 3.0) -> List[SentimentDivergenceSignal]:
        """Get recent divergence signals above threshold."""
        return [d for d in self._divergence_history[-50:] if d.score >= min_score]


# ===================================================================
# 6. NewsImpactAnalyzer
# ===================================================================

class NewsImpactAnalyzer:
    """
    Analyzes news impact with categorization, scoring, and decay functions.
    """

    # Impact base scores by category
    CATEGORY_IMPACT = {
        "regulatory": 0.8,
        "hack": 0.9,
        "adoption": 0.6,
        "partnership": 0.5,
        "general": 0.3,
    }

    def __init__(self, decay_hours: float = 48.0):
        """
        decay_hours: how long until news impact is half gone (half-life).
        """
        self.decay_hours = decay_hours
        self._news_history: List[dict] = []
        self._analyzer = NLPSentimentAnalyzer()

    def analyze_news(self, title: str, body: str = "", source: str = "", url: str = "") -> dict:
        """
        Analyze a single news article.
        Returns dict with category, sentiment, impact score, decay, etc.
        """
        full_text = f"{title}. {body}" if body else title
        now = datetime.now(timezone.utc)

        # Classify
        category, cat_conf = self._analyzer.classify_news_category(full_text)

        # Sentiment
        sentiment_score, sentiment_conf = self._analyzer.analyze_text(full_text)

        # Entities
        entities = self._analyzer.extract_entities(full_text)

        # Impact scoring
        base_impact = self.CATEGORY_IMPACT.get(category, 0.3)
        # Amplify by sentiment magnitude (stronger opinions = bigger impact)
        magnitude_factor = abs(sentiment_score) * 0.5 + 0.5
        # Amplify by source credibility
        source_factor = self._get_source_factor(source)
        # Entity count amplifies
        entity_factor = min(2.0, 1.0 + len(entities) * 0.3)

        impact_score = base_impact * magnitude_factor * source_factor * entity_factor
        impact_score = min(1.0, impact_score)

        news_item = {
            "id": hashlib.md5(f"{full_text}{now.timestamp()}".encode()).hexdigest()[:12],
            "timestamp": now.isoformat(),
            "title": title,
            "source": source,
            "url": url,
            "category": category,
            "category_confidence": cat_conf,
            "sentiment_score": round(sentiment_score, 4),
            "sentiment_confidence": round(sentiment_conf, 4),
            "impact_score": round(impact_score, 4),
            "entities": entities,
            "decay_hours": self.decay_hours,
        }

        self._news_history.append(news_item)
        return news_item

    def _get_source_factor(self, source: str) -> float:
        """Credibility factor for news sources."""
        credible = {
            "reuters", "bloomberg", "coindesk", "cointelegraph", "wsj",
            "financial times", "cnbc", "decrypt", "the block",
        }
        source_lower = source.lower()
        for c in credible:
            if c in source_lower:
                return 1.5
        return 1.0

    def get_decayed_impact(self, news_item: dict, current_time: datetime = None) -> float:
        """Calculate remaining impact after decay."""
        current_time = current_time or datetime.now(timezone.utc)
        news_time = datetime.fromisoformat(news_item["timestamp"])
        hours_elapsed = (current_time - news_time).total_seconds() / 3600.0

        if hours_elapsed <= 0:
            return news_item["impact_score"]

        # Exponential decay: impact = initial * 0.5^(hours/half_life)
        decay_factor = 0.5 ** (hours_elapsed / self.decay_hours)
        return news_item["impact_score"] * decay_factor

    def get_current_impact(
        self,
        asset: Optional[str] = None,
        max_age_hours: float = 168,  # 1 week
    ) -> Dict[str, Any]:
        """Get aggregate current news impact for an asset or all."""
        now = datetime.now(timezone.utc)
        total_impact = 0.0
        recent_news_by_category = defaultdict(list)

        for item in self._news_history:
            item_time = datetime.fromisoformat(item["timestamp"])
            age_hours = (now - item_time).total_seconds() / 3600.0

            if age_hours > max_age_hours:
                continue

            if asset:
                entities = [e["name"] for e in item.get("entities", [])]
                if asset not in entities:
                    continue

            decayed = self.get_decayed_impact(item, now)
            total_impact += decayed
            recent_news_by_category[item["category"]].append({
                "title": item["title"][:80],
                "decayed_impact": round(decayed, 4),
                "age_hours": round(age_hours, 1),
                "sentiment": item["sentiment_score"],
            })

        # News frequency anomaly detection
        anomaly = self._detect_news_frequency_anomaly(asset)

        return {
            "asset": asset or "ALL",
            "total_active_impact": round(total_impact, 4),
            "by_category": dict(recent_news_by_category),
            "recent_article_count": len(recent_news_by_category),
            "frequency_anomaly": anomaly,
        }

    def _detect_news_frequency_anomaly(self, asset: Optional[str] = None) -> Dict[str, Any]:
        """
        Detect unusual news frequency.
        A sudden spike in news volume often precedes large moves.
        """
        if len(self._news_history) < 20:
            return {"is_anomalous": False, "reason": "insufficient_data"}

        now = datetime.now(timezone.utc)
        # Recent 6 hours vs prior 48 hours
        recent = sum(1 for n in self._news_history[-50:]
                     if (now - datetime.fromisoformat(n["timestamp"])).total_seconds() < 21600
                     and (not asset or asset in [e["name"] for e in n.get("entities", [])]))

        older_total = sum(1 for n in self._news_history[-200:]
                          if (now - datetime.fromisoformat(n["timestamp"])).total_seconds() >= 21600
                          and (not asset or asset in [e["name"] for e in n.get("entities", [])]))

        # Rate per hour
        recent_rate = recent / 6.0
        older_rate = older_total / 48.0 if older_total > 0 else recent_rate

        z_score = (recent_rate - older_rate) / max(older_rate, 0.5)

        return {
            "is_anomalous": z_score > 2.0,
            "z_score": round(z_score, 2),
            "recent_rate_per_hour": round(recent_rate, 1),
            "baseline_rate_per_hour": round(older_rate, 1),
            "meaning": "news_spike" if z_score > 2 else "normal",
        }


# ===================================================================
# Composite SentimentEngine
# ===================================================================

class SentimentEngine:
    """
    Master sentiment engine combining all sub-analyzers.
    Provides a unified interface for multi-source sentiment analysis.
    """

    def __init__(self):
        self.nlp = NLPSentimentAnalyzer()
        self.fear_greed = FearGreedIndex()
        self.social = SocialAggregator()
        self.onchain = OnChainSentiment()
        self.divergence = SentimentDivergence()
        self.news = NewsImpactAnalyzer()

        self.all_signals: List[SentimentSignal] = []
        self.divergence_signals: List[SentimentDivergenceSignal] = []

    def process_news_article(
        self, title: str, body: str = "", source: str = "", url: str = ""
    ) -> dict:
        """Process a news article through the full pipeline."""
        result = self.news.analyze_news(title, body, source, url)
        signals = self.nlp.analyze_news([
            NewsItem(
                id=result["id"],
                timestamp=datetime.fromisoformat(result["timestamp"]),
                title=title, body=body, source=source, url=url,
            )
        ])
        self.all_signals.extend(signals)
        return {"news_result": result, "signals": signals}

    def run_full_analysis(
        self,
        price_data: pd.DataFrame = None,
        asset: str = "BTC",
        price: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Run full sentiment analysis pipeline.
        Returns comprehensive sentiment report.
        """
        now = datetime.now(timezone.utc)

        # Generate mock social data
        twitter_signals = self.social.track_twitter(query=asset.lower())
        reddit_signals = self.social.track_reddit(query=asset.lower())
        social_composite = self.social.aggregate_platform_sentiment(
            twitter_signals + reddit_signals
        )

        # Telegram/Discord stats
        telegram_stats = self.social.track_telegram()
        discord_stats = self.social.track_discord()

        # Fear & Greed
        fg_result = self.fear_greed.compute(
            price_data=price_data,
            social_signals=twitter_signals + reddit_signals,
        )
        fg_signal = self.fear_greed.get_signal()

        # On-chain (mock values if no real data)
        exchange_sent = self.onchain.compute_exchange_flow_sentiment(
            inflow=1250, outflow=1780, avg_inflow=1100, avg_outflow=1200
        )
        whale_sent = self.onchain.compute_whale_sentiment(
            whale_balance_change_pct=2.3, large_txns_buy=45, large_txns_sell=32
        )
        stablecoin_sent = self.onchain.compute_stablecoin_flow_sentiment(
            stablecoin_inflow_btc=850000, stablecoin_outflow_btc=620000,
            exchange_stablecoin_balance_pct_change=3.1,
        )
        nvt_sent = self.onchain.compute_nvt_sentiment(nvt_ratio=28.5)
        mvrv_sent = self.onchain.compute_mvrv_sentiment(mvrv_ratio=2.1)
        onchain_composite = self.onchain.aggregate_onchain_sentiment(
            exchange_sent, whale_sent, stablecoin_sent, nvt_sent, mvrv_sent
        )

        # Divergence
        div_signal = self.divergence.update(asset, price, social_composite)
        if div_signal:
            self.divergence_signals.append(div_signal)

        # Composite sentiment
        all_active = [social_composite, fg_signal, onchain_composite]
        composite_score = np.mean([s.score for s in all_active])
        composite_conf = np.mean([s.confidence for s in all_active])

        composite = SentimentSignal(
            timestamp=now,
            asset=asset,
            source="composite",
            score=float(composite_score),
            confidence=float(composite_conf),
            details={
                "fear_greed_index": fg_result["index"],
                "fear_greed_classification": fg_result["classification"],
                "social_score": social_composite.score,
                "onchain_score": onchain_composite.score,
            },
        )

        self.all_signals.append(composite)

        # News impact context
        news_impact = self.news.get_current_impact(asset)

        report = {
            "timestamp": now.isoformat(),
            "asset": asset,
            "price": price,
            "composite_sentiment": composite_score,
            "fear_greed": fg_result,
            "social": {
                "composite": social_composite.to_dict(),
                "platform_summary": self.social.get_platform_summary(),
                "telegram": telegram_stats,
                "discord": discord_stats,
            },
            "onchain": {
                "composite": onchain_composite.to_dict(),
                "exchange_flow_sentiment": exchange_sent,
                "whale_sentiment": whale_sent,
                "stablecoin_sentiment": stablecoin_sent,
                "nvt_sentiment": nvt_sent,
                "mvrv_sentiment": mvrv_sent,
            },
            "divergence": div_signal.to_dict() if div_signal else None,
            "news_impact": news_impact,
        }
        return report

    def get_signal_summary(self, asset: Optional[str] = None) -> pd.DataFrame:
        """Return a DataFrame of all signals, optionally filtered by asset."""
        signals = self.all_signals
        if asset:
            signals = [s for s in signals if s.asset == asset]

        if not signals:
            return pd.DataFrame()

        rows = []
        for s in signals:
            rows.append({
                "timestamp": s.timestamp,
                "asset": s.asset,
                "source": s.source,
                "score": s.score,
                "confidence": s.confidence,
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("timestamp", ascending=False)
        return df

    def get_divergence_summary(self, min_score: float = 3.0) -> pd.DataFrame:
        """Get divergences as DataFrame."""
        signals = self.divergence.get_recent_divergences(min_score)
        if not signals:
            return pd.DataFrame()
        return pd.DataFrame([
            {
                "timestamp": s.timestamp,
                "asset": s.asset,
                "type": s.div_type,
                "score": s.score,
                "description": s.description,
            }
            for s in signals
        ])

