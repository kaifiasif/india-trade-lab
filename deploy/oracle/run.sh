#!/usr/bin/env bash
# Run one scheduled India Trade Lab job with the private env files loaded.
# Usage: run.sh premarket | market | aftermarket | observatory
# Paper research only: nothing here places an order.
set -euo pipefail

REPO="${REPO:-$HOME/india-trade-lab}"
DATA="$REPO/data/observatory"
CONFIG="$DATA/pipeline.json"
cd "$REPO"

# Secrets (SMTP_PASSWORD, model API key, KITE_API_KEY/SECRET) and today's Kite token.
for file in "$HOME/.india-trade-lab.secrets" "$HOME/.india-trade-lab.env"; do
  # shellcheck disable=SC1090
  [ -f "$file" ] && source "$file"
done

trading_day() {
  python3 - "$DATA/sessions.json" <<'PY'
import datetime as dt, json, sys
ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
sessions = json.load(open(sys.argv[1]))["sessions"]
sys.exit(0 if str(dt.datetime.now(ist).date()) in sessions else 1)
PY
}

job="${1:-}"
case "$job" in
  observatory)
    exec python3 scripts/observatory.py --data-dir "$DATA" ;;
esac

if ! trading_day; then
  echo "Not an NSE trading day in sessions.json; skipping $job."
  exit 0
fi

case "$job" in
  premarket)
    python3 scripts/reference.py --db "$DATA/reference.sqlite" refresh \
      || echo "NSE reference refresh failed; the report will use cached reference data."
    python3 scripts/evidence.py collect --config "$CONFIG" \
      || echo "News collection failed; the report will use previously collected headlines."
    exec python3 scripts/premarket.py --config "$CONFIG" --email ;;
  market)
    exec python3 scripts/market_service.py --config "$CONFIG" --refresh-india --prepare ;;
  aftermarket)
    # Today's completed session into history, while today's Kite token is still valid.
    exec python3 scripts/data_sync.py --config "$CONFIG" --days 90 --max-symbols 3 ;;
  *)
    echo "Usage: run.sh premarket | market | aftermarket | observatory" >&2
    exit 64 ;;
esac
