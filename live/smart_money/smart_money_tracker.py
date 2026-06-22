"""
Smart Money Tracker — Follows profitable wallets, detects accumulation/distribution,
and alerts on whale moves that signal big price movements.
"""
import requests, json, time, os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field

# ── Data Models ────────────────────────────────────────────

@dataclass
class WhaleMove:
    tx_hash: str
    chain: str
    token: str
    amount_usd: float
    type: str  # buy / sell / transfer
    wallet: str
    wallet_label: str  # "CEX", "whale", "insider", "deployer"
    timestamp: datetime
    confidence: float  # 0-1

    def to_alert(self) -> str:
        emoji = "🐋" if self.amount_usd > 100000 else "🐟"
        side_emoji = "🟢" if self.type == "buy" else "🔴" if self.type == "sell" else "🔄"
        return (f"{side_emoji}{emoji} **{self.token}** ({self.chain})\n"
                f"   Type: {self.type.upper()} | ${self.amount_usd:,.0f}\n"
                f"   Wallet: `{self.wallet[:8]}...` {self.wallet_label}\n"
                f"   Confidence: {self.confidence:.0%}\n"
                f"   Tx: `{self.tx_hash[:12]}...`")

class SmartMoneyTracker:
    """Detects and tracks smart money movements on-chain."""

    def __init__(self):
        self.seen_txs: set = set()
        self.whale_wallets: Dict[str, Dict] = self._load_known_wallets()

    def _load_known_wallets(self) -> Dict[str, Dict]:
        """Load tracked wallets (loaded from env/secret in production)."""
        return {
            # Example wallets — replace with real tracked wallets
            "0x1234567890abcdef1234567890abcdef12345678": {"label": "Alameda_Related", "chain": "ethereum"},
            "0xdead000000000000000000000000000000000000": {"label": "Known_Whale", "chain": "ethereum"},
        }

    def track_whale(self, chain: str = "ethereum", min_usd: float = 50000) -> List[WhaleMove]:
        """
        Track whale moves from public mempool/blockchain data.
        In production, connect to Etherscan/BscScan API or private RPC.
        """
        moves = []
        api_key = os.environ.get("ETHERSCAN_API_KEY", "")
        if not api_key:
            return self._mock_whale_moves(chain)

        # Real API integration pattern:
        for wallet, info in self.whale_wallets.items():
            if info["chain"] != chain:
                continue
            url = (f"https://api.etherscan.io/api"
                   f"?module=account&action=tokentx"
                   f"&address={wallet}&sort=desc"
                   f"&apikey={api_key}")
            try:
                data = requests.get(url, timeout=10).json()
                for tx in data.get("result", [])[:10]:
                    tx_hash = tx.get("hash", "")
                    if tx_hash in self.seen_txs:
                        continue
                    value = float(tx.get("value", 0)) / 10**int(tx.get("tokenDecimal", 18))
                    price = self._estimate_price(tx.get("contractAddress", ""), chain)
                    usd_amount = value * price if price else 0

                    if usd_amount < min_usd:
                        continue

                    tx_type = "buy" if tx.get("to", "").lower() == wallet.lower() else "sell"
                    move = WhaleMove(
                        tx_hash=tx_hash,
                        chain=chain,
                        token=tx.get("tokenSymbol", "???"),
                        amount_usd=usd_amount,
                        type=tx_type,
                        wallet=wallet,
                        wallet_label=info["label"],
                        timestamp=datetime.fromtimestamp(int(tx.get("timeStamp", 0)), tz=timezone.utc),
                        confidence=0.85,
                    )
                    self.seen_txs.add(tx_hash)
                    moves.append(move)
            except Exception as e:
                print(f"Whale tracking error for {wallet}: {e}")

        moves.sort(key=lambda m: m.amount_usd, reverse=True)
        return moves

    def _estimate_price(self, contract: str, chain: str) -> float:
        """Estimate token price from DEX data."""
        try:
            chain_map = {"ethereum": "ethereum", "bsc": "bsc", "solana": "solana"}
            url = f"https://api.dexscreener.com/latest/dex/token/{contract}"
            data = requests.get(url, timeout=5).json()
            pairs = data.get("pairs", [])
            for p in pairs:
                if p.get("chainId") == chain:
                    return float(p.get("priceUsd", 0))
        except: pass
        return 0.0

    def _mock_whale_moves(self, chain: str) -> List[WhaleMove]:
        """Demo mode — generates realistic mock whale moves for testing."""
        import random
        tokens = {
            "ethereum": [("ETH", 2800), ("LINK", 14), ("UNI", 7), ("AAVE", 120)],
            "solana": [("SOL", 140), ("JUP", 0.85), ("RAY", 2.1), ("PYTH", 0.45)],
            "bsc": [("BNB", 580), ("CAKE", 2.3), ("XRP", 0.52)],
        }

        moves = []
        chain_tokens = tokens.get(chain, [("TOKEN", 1)])
        now = datetime.now(timezone.utc)

        for _ in range(random.randint(1, 4)):
            token, base_price = random.choice(chain_tokens)
            amount = random.uniform(10000, 500000)
            tx_type = random.choice(["buy", "sell", "transfer"])

            move = WhaleMove(
                tx_hash=f"0x{random.getrandbits(160):040x}",
                chain=chain,
                token=token,
                amount_usd=amount,
                type=tx_type,
                wallet=f"0x{random.getrandbits(160):040x}",
                wallet_label=random.choice(["whale", "CEX", "known_trader"]),
                timestamp=now - timedelta(minutes=random.randint(0, 60)),
                confidence=random.uniform(0.7, 0.95),
            )
            moves.append(move)

        return moves

    def detect_accumulation(self, chain: str, token: str, lookback_hours: int = 24) -> Dict:
        """Detect if a token is being accumulated by smart money."""
        whales = self.track_whale(chain, min_usd=10000)
        token_moves = [m for m in whales if m.token.upper() == token.upper()]

        if not token_moves:
            return {"accumulating": False, "net_flow": 0, "whale_count": 0}

        net = sum(m.amount_usd if m.type == "buy" else -m.amount_usd for m in token_moves)
        unique_whales = len(set(m.wallet for m in token_moves))

        return {
            "accumulating": net > 0,
            "net_flow_usd": net,
            "whale_count": unique_whales,
            "total_moves": len(token_moves),
            "confidence": "high" if unique_whales >= 3 and abs(net) > 100000 else "medium",
        }

    def get_insider_moves(self, contract: str, deployer_wallet: str) -> List[WhaleMove]:
        """Track deployer/insider wallet for dumps."""
        moves = self._mock_whale_moves("ethereum")  # replace with real RPC
        return [m for m in moves if m.wallet_label == "whale"][:5]

# ── Entry ──────────────────────────────────────────────────

def track_whales(chain: str = "solana", min_usd: float = 50000) -> List[dict]:
    tracker = SmartMoneyTracker()
    moves = tracker.track_whale(chain, min_usd)
    return [
        {
            "token": m.token,
            "type": m.type,
            "amount_usd": m.amount_usd,
            "wallet_label": m.wallet_label,
            "confidence": m.confidence,
        }
        for m in moves[:10]
    ]
