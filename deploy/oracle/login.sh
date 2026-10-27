#!/usr/bin/env bash
# Daily Kite login (you log in yourself, with 2FA), then restart the market service
# so it picks up today's token. Run it each trading morning before 09:05.
set -euo pipefail
REPO="${REPO:-$HOME/india-trade-lab}"
cd "$REPO"
# shellcheck disable=SC1090
source "$HOME/.india-trade-lab.secrets"
python3 scripts/kite_login.py
if systemctl is-active --quiet india-trade-lab-market.service; then
  sudo systemctl restart india-trade-lab-market.service
  echo "Market service restarted with today's token."
fi
