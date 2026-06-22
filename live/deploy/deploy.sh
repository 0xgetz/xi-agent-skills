#!/bin/bash
# deploy.sh — Deploy the trading bot to production
# Usage: bash deploy.sh [railway|render|fly|docker]

set -e

APP_NAME="gumloop-alpha-bot"
echo "🚀 Deploying $APP_NAME..."

# ── Docker Build ──────────────────────────────────────────
docker_build() {
    echo "🐳 Building Docker image..."
    docker build -t $APP_NAME .
    echo "✅ Built $APP_NAME"
    docker run --rm \
        -e TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN" \
        -e TELEGRAM_CHAT_ID="$TELEGRAM_CHAT_ID" \
        -e CAPITAL_USD="${CAPITAL_USD:-500}" \
        -e RPC_URL="$RPC_URL" \
        $APP_NAME python alerts/telegram_bot.py all
}

# ── Railway Deploy ────────────────────────────────────────
deploy_railway() {
    echo "🚂 Deploying to Railway..."
    railway up --service $APP_NAME
    echo "✅ Deployed to Railway"
    echo "   Set env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, CAPITAL_USD"
}

# ── Render Deploy ─────────────────────────────────────────
deploy_render() {
    echo "🎨 Deploying to Render..."
    render deploy --service $APP_NAME
    echo "✅ Deployed to Render"
}

# ── Fly.io Deploy ─────────────────────────────────────────
deploy_fly() {
    echo "🪰 Deploying to Fly.io..."
    flyctl deploy --app $APP_NAME
    echo "✅ Deployed to Fly.io"
}

case "${1:-docker}" in
    docker) docker_build ;;
    railway) deploy_railway ;;
    render) deploy_render ;;
    fly) deploy_fly ;;
    all)
        docker_build
        echo "---"
        echo "Also available: railway, render, fly"
        ;;
    *)
        echo "Usage: $0 [docker|railway|render|fly]"
        exit 1
        ;;
esac
