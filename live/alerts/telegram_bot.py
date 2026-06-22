"""
Telegram Alpha Bot — Production bot that:
1. Scans for alpha (new tokens, momentum, patterns)
2. Filters with risk scoring
3. Sends actionable trade alerts to Telegram
4. Tracks positions and PnL
"""
import os, sys, json, time, asyncio
from datetime import datetime, timezone
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from execution.alpha_discovery import AlphaEngine, scan_for_alpha
    from execution.live_trader import PositionManager, TradingConfig, MarketDataFeed
    ALPHA = True
except ImportError:
    ALPHA = False
    print("Alpha modules not found — running in standalone mode")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

def send(text: str):
    """Send message to Telegram."""
    import requests
    if not BOT_TOKEN or not CHAT_ID:
        print(f"[ALERT] {text}")
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={
            "chat_id": CHAT_ID, "text": text,
            "parse_mode": "Markdown", "disable_web_page_preview": True
        }, timeout=10)
    except Exception as e:
        print(f"Send error: {e}")

def run_alpha_scan():
    """Run alpha discovery and send best signals to Telegram."""
    if not ALPHA:
        send("⚠️ Alpha modules not loaded")
        return

    send("🔄 **Scanning for Alpha...**")
    engine = AlphaEngine()

    chains = ["solana", "ethereum", "bsc", "base"]
    all_signals = []

    for chain in chains:
        dex_sigs = engine.scan_dexscreener(chain)
        cex_sigs = engine.scan_new_tokens(chain)
        all_signals.extend(dex_sigs + cex_sigs)

    # Sort by score (safest first) and volume (highest first)
    all_signals.sort(key=lambda s: (10 - s.risk_score) * 10 + min(s.volume_24h / 1000, 100), reverse=True)

    if not all_signals:
        send("😴 No strong alpha signals right now. Market quiet or already scanned.")
        return

    # Top 3 signals
    for s in all_signals[:3]:
        send(s.to_alert())

    # Summary
    send(f"📊 **Scan Complete** — {len(all_signals)} signals | Showing top 3")

def run_market_analysis():
    """Analyze current market conditions and suggest actionable trades."""
    import requests as rq
    send("📈 **Market Analysis**")

    # Check BTC dominance and sentiment
    try:
        data = rq.get("https://api.coingecko.com/api/v3/global", timeout=10).json()
        btc_d = data.get("data", {}).get("market_cap_percentage", {}).get("btc", 0)
        total_mcap = data.get("data", {}).get("total_market_cap", {}).get("usd", 0)

        msg = (f"🌍 **Global Market**\n"
               f"   Total MCap: ${total_mcap:,.0f}\n"
               f"   BTC Dominance: {btc_d:.1f}%\n")

        if btc_d < 40:
            msg += "   🟢 **Altseason** — BTC dominance low, alts pumping"
        elif btc_d > 60:
            msg += "   🟠 **BTC season** — Money flowing to Bitcoin"
        else:
            msg += "   🔵 **Mixed** — No clear dominance"

        send(msg)
    except Exception as e:
        send(f"Market analysis error: {e}")

def run_trading_session():
    """Run a full automated trading session simulation."""
    send("⚡ **Trading Session Started**")

    if not ALPHA:
        send("⚠️ Live trading requires full modules")
        return

    cfg = TradingConfig()
    pm = PositionManager(cfg)
    feed = MarketDataFeed()

    # Phase 1: Scan
    signals = scan_for_alpha("solana")

    for sig in signals[:5]:
        if sig["risk_score"] > 7:
            send(f"⛔ SKIP {sig['symbol']} — Risk too high ({sig['risk_score']}/10)")
            continue

        side = "long" if sig["price_change_5m"] < 0.1 else "long"  # always long for now
        # Check if we can open
        if pm.can_open(sig["symbol"]):
            pos = pm.open_position(sig["symbol"], side, sig["price"], sig["reason"])
            if pos:
                send(f"✅ Position opened: ${sig['symbol']} @ ${sig['price']:.8f}")

    # Phase 2: Monitor (simulated prices)
    for symbol in [p.symbol for p in pm.positions]:
        price = feed.get_price(symbol)
        if price:
            closed = pm.check_stops({symbol: price})

    # Phase 3: Summary
    send(pm.summary())

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scan"

    if cmd == "scan":
        run_alpha_scan()
    elif cmd == "analyze":
        run_market_analysis()
    elif cmd == "trade":
        run_trading_session()
    elif cmd == "all":
        run_market_analysis()
        time.sleep(2)
        run_alpha_scan()
        time.sleep(2)
        run_trading_session()
    else:
        send(f"Unknown command: {cmd}")
