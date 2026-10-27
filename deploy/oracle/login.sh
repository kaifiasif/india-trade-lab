#!/usr/bin/env bash
# Daily Kite login (you log in yourself, with 2FA), then restart the market service
# so it picks up today's token. Run it each trading morning before 09:05.
set -euo pipefail
REPO="${REPO:-$HOME/india-trade-lab}"
cd "$REPO"
# shellcheck disable=SC1090
source "$HOME/.india-trade-lab.secrets"
python3 scripts/kite_login.py

# Two pre-trade checks need a person, once per stock per day: you look at NSE's
# surveillance (ASM/GSM) list and today's announcements, and say where you looked.
# Without this, entries stay blocked; exits are never blocked.
CONFIG="$REPO/data/observatory/pipeline.json"
symbols=$(python3 -c 'import json,sys; print(" ".join(i["symbol"] for i in json.load(open(sys.argv[1]))["instruments"]))' \
  "$REPO/data/observatory/universe.json" 2>/dev/null || true)
if [ -n "$symbols" ]; then
  echo "Check NSE's ASM/GSM surveillance lists and today's corporate announcements, then answer:"
  for symbol in $symbols; do
    python3 scripts/pretrade.py attest --config "$CONFIG" --symbol "$symbol"
  done
fi
if systemctl is-active --quiet india-trade-lab-market.service; then
  sudo systemctl restart india-trade-lab-market.service
  echo "Market service restarted with today's token."
fi
