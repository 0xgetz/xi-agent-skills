#!/bin/bash
# run_bot.sh — Start the alpha trading bot
set -e

# Load env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

echo "Starting Gumloop Alpha Bot..."
echo "  Capital: $CAPITAL_USD USD"
echo "  Risk: ${RISK_PER_TRADE:-2}% per trade"
echo ""

# Run all scans
python alerts/telegram_bot.py all
