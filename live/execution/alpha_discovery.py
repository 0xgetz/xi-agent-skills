import requests, json, time, os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

# ── Data Sources ───────────────────────────────────────────

DEXSCREENER_API = "https://api.dexscreener.com/latest/dex"
COINGECKO_API = "https://api.coingecko.com/api/v3"
BIRDEYE_API = "https://public-api.birdeye.so/public"
SOLSCAN_API = "https://api.solscan.io"

# ── Alpha Signal Types ─────────────────────────────────────

@dataclass
class AlphaSignal:
    symbol: str
    chain: str
    price_usd: float
    liquidity_usd: float
    volume_24h: float
    fdv: float
    price_change_5m: float
    price_change_1h: float
    holders: Optional[int] = None
    age_hours: float = 0.0
    risk_score: float = 0.0
    signal_type: str = ""
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_early(self) -> bool:
        return self.age_hours < 24 and self.liquidity_usd > 10000

    @property
    def is_moonbag(self) -> bool:
        return self.volume_24h > self.fdv * 0.3

    def to_alert(self) -> str:
        return (f"🚀 **{self.symbol}** ({self.chain})\n"
                f"   Price: ${self.price_usd:.8f}\n"
                f"   Liq: ${self.liquidity_usd:,.0f} | Vol 24h: ${self.volume_24h:,.0f}\n"
                f"   FDV: ${self.fdv:,.0f}\n"
                f"   5m: {self.price_change_5m:+.1%} | 1h: {self.price_change_1h:+.1%}\n"
                f"   Age: {self.age_hours:.1f}h | Risk: {self.risk_score:.0f}/10\n"
                f"   {self.reason}")

class AlphaEngine:
    """Multi-chain alpha discovery and scoring engine."""

    def __init__(self):
        self.seen_tokens: set = set()
        self.alerts: List[AlphaSignal] = []
        self.score_threshold = 60  # min score to alert

    def scan_dexscreener(self, chain: str = "solana", min_liq: float = 5000) -> List[AlphaSignal]:
        """Scan newly created pairs on a DEX chain."""
        signals = []
        try:
            url = f"{DEXSCREENER_API}/search/?q={chain}"
            data = requests.get(url, timeout=10).json()
            pairs = data.get("pairs", [])

            for pair in pairs[:50]:  # top 50
                pair_addr = pair.get("pairAddress", "")
                if pair_addr in self.seen_tokens:
                    continue

                base = pair.get("baseToken", {})
                quote = pair.get("quoteToken", {})
                if quote.get("symbol") != "USDC" and quote.get("symbol") != "WETH":
                    continue

                symbol = base.get("symbol", "")
                created = pair.get("pairCreatedAt", 0)
                age_hours = (time.time() * 1000 - created) / 3600000 if created else 999

                liq_usd = float(pair.get("liquidity", {}).get("usd", 0) or 0)
                if liq_usd < min_liq:
                    continue

                signal = AlphaSignal(
                    symbol=symbol,
                    chain=chain,
                    price_usd=float(pair.get("priceUsd", 0) or 0),
                    liquidity_usd=liq_usd,
                    volume_24h=float(pair.get("volume", {}).get("h24", 0) or 0),
                    fdv=float(pair.get("fdv", 0) or 0),
                    price_change_5m=float(pair.get("priceChange", {}).get("m5", 0) or 0),
                    price_change_1h=float(pair.get("priceChange", {}).get("h1", 0) or 0),
                    age_hours=age_hours,
                )
                signal.risk_score = self._calculate_risk(signal)
                signal.signal_type = self._classify(signal)
                signal.reason = self._reason(signal)

                self.seen_tokens.add(pair_addr)

                if self._should_alert(signal):
                    signals.append(signal)
                    self.alerts.append(signal)

        except Exception as e:
            print(f"DEXScreener scan error: {e}")

        return signals

    def scan_new_tokens(self, chain: str = "ethereum") -> List[AlphaSignal]:
        """Scan for newly deployed tokens via API."""
        signals = []
        chains = {
            "ethereum": "ethereum",
            "bsc": "bsc",
            "base": "base",
            "arbitrum": "arbitrum",
            "polygon": "polygon",
        }
        chain_id = chains.get(chain, chain)

        try:
            url = f"{COINGECKO_API}/coins/markets"
            params = {"vs_currency": "usd", "order": "volume_desc", "per_page": 50, "page": 1}
            data = requests.get(url, params=params, timeout=10).json()

            for coin in data:
                coin_id = coin.get("id", "")
                if coin_id in self.seen_tokens:
                    continue

                age = coin.get("ath_date", "")
                age_hours = 999
                if age:
                    try:
                        dt = datetime.fromisoformat(age.replace("Z", "+00:00"))
                        age_hours = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
                    except: pass

                signal = AlphaSignal(
                    symbol=coin.get("symbol", "").upper(),
                    chain=chain_id,
                    price_usd=coin.get("current_price", 0) or 0,
                    liquidity_usd=coin.get("market_cap", 0) or 0,
                    volume_24h=coin.get("total_volume", 0) or 0,
                    fdv=coin.get("fully_diluted_valuation", 0) or 0,
                    price_change_5m=0,
                    price_change_1h=coin.get("price_change_percentage_1h_in_currency", 0) or 0,
                    age_hours=age_hours,
                )
                signal.risk_score = self._calculate_risk(signal)
                signal.signal_type = "NEW_LISTING"
                signal.reason = f"Listed on CMC/CoinGecko with ${signal.volume_24h:,.0f} volume"

                self.seen_tokens.add(coin_id)
                if self._should_alert(signal):
                    signals.append(signal)
                    self.alerts.append(signal)

        except Exception as e:
            print(f"New tokens scan error: {e}")

        return signals

    def _calculate_risk(self, s: AlphaSignal) -> float:
        """Score 0 (safe) to 10 (very risky)."""
        risk = 5.0
        if s.liquidity_usd > 100000: risk -= 2
        elif s.liquidity_usd > 50000: risk -= 1
        elif s.liquidity_usd < 10000: risk += 2

        if s.volume_24h > s.fdv * 0.5: risk -= 1  # healthy volume
        if s.fdv < 100000: risk += 2  # very small cap
        if s.age_hours < 1: risk += 1  # brand new
        if s.price_change_5m > 0.5: risk += 1.5  # pump potential dump

        return max(0, min(10, risk))

    def _classify(self, s: AlphaSignal) -> str:
        if s.age_hours < 1 and s.volume_24h > 50000: return "HOT_NEW"
        if s.volume_24h > s.fdv * 0.3: return "HIGH_MOMENTUM"
        if s.liquidity_usd > 50000 and s.fdv < 500000: return "UNDERVALUED"
        if s.price_change_5m > 0.2: return "PUMPING"
        return "WATCH"

    def _reason(self, s: AlphaSignal) -> str:
        reasons = []
        if s.is_early: reasons.append("Early entry window")
        if s.fdv < 100000: reasons.append(f"Low FDV (${s.fdv:,.0f})")
        if s.volume_24h > 50000: reasons.append(f"Strong volume ${s.volume_24h:,.0f}")
        if s.liquidity_usd < 10000: reasons.append("Low liq — high risk")
        return " | ".join(reasons) if reasons else "Monitor"

    def _should_alert(self, s: AlphaSignal) -> bool:
        score = (10 - s.risk_score) * 10  # convert 0-10 risk to 0-100 score
        volume_score = min(s.volume_24h / 100000, 1) * 20
        liquidity_score = min(s.liquidity_usd / 50000, 1) * 20
        early_score = max(0, (24 - s.age_hours) / 24) * 30
        total = score + volume_score + liquidity_score + early_score
        return total >= self.score_threshold

# ── Quick scan entry point ─────────────────────────────────

def scan_for_alpha(chain: str = "solana") -> List[dict]:
    """Quick scan: returns actionable alpha signals as dicts."""
    engine = AlphaEngine()
    dex_signals = engine.scan_dexscreener(chain)
    cex_signals = engine.scan_new_tokens(chain)

    all_signals = dex_signals + cex_signals
    all_signals.sort(key=lambda s: s.volume_24h, reverse=True)

    return [
        {
            "symbol": s.symbol,
            "chain": s.chain,
            "price": s.price_usd,
            "liquidity": s.liquidity_usd,
            "volume_24h": s.volume_24h,
            "fdv": s.fdv,
            "age_hours": round(s.age_hours, 1),
            "risk_score": round(s.risk_score, 1),
            "signal_type": s.signal_type,
            "reason": s.reason,
        }
        for s in all_signals[:10]
    ]

if __name__ == "__main__":
    results = scan_for_alpha("solana")
    print(json.dumps(results, indent=2))
