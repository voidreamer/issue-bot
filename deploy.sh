#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# deploy.sh — Deploy issue-bot on your GCE instance
# Run this ON the server (or paste commands into SSH)
# ============================================================

APP_DIR="/opt/issue-bot"
SERVICE_NAME="issue-bot"

echo "==> Creating app directory..."
sudo mkdir -p "$APP_DIR"

echo "==> Creating system user (if not exists)..."
id -u issuebot &>/dev/null || sudo useradd -r -s /usr/sbin/nologin issuebot

echo "==> Copying files..."
sudo cp app.py requirements.txt "$APP_DIR/"
sudo cp -r issue_bot/ "$APP_DIR/issue_bot/"

echo "==> Creating data directory..."
sudo mkdir -p "$APP_DIR/data"

echo "==> Setting up Python venv..."
sudo python3 -m venv "$APP_DIR/venv"
sudo "$APP_DIR/venv/bin/pip" install --upgrade pip
sudo "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

echo "==> Installing systemd service..."
sudo cp issue-bot.service /etc/systemd/system/
sudo systemctl daemon-reload

# Remind about .env
if [ ! -f "$APP_DIR/.env" ]; then
    echo ""
    echo "⚠️  IMPORTANT: Create $APP_DIR/.env with your secrets before starting!"
    echo "   See .env.example for the template."
    echo ""
    echo "   sudo nano $APP_DIR/.env"
    echo ""
fi

echo "==> Setting ownership..."
sudo chown -R issuebot:issuebot "$APP_DIR"

echo ""
echo "✅ Deployed! Next steps:"
echo "   1. Create/edit $APP_DIR/.env with your tokens"
echo "   2. sudo systemctl enable --now $SERVICE_NAME"
echo "   3. sudo systemctl status $SERVICE_NAME"
echo "   4. Configure Nginx reverse proxy (see SETUP.md)"
echo ""
