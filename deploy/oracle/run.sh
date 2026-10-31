#!/usr/bin/env bash
# Run one scheduled India Trade Lab job with the private env files loaded.
# Usage: run.sh premarket | open | confirm | market | aftermarket | watchdog | backup | observatory
# Paper research only: nothing here places an order.
set -euo pipefail

REPO="${REPO:-$HOME/india-trade-lab}"
DATA="$REPO/data/observatory"
CONFIG="$DATA/pipeline.json"
cd "$REPO"

# Secrets (SMTP_PASSWORD, model API key, KITE_API_KEY/SECRET) and today's Kite token.
# Keys and the Kite token saved from the dashboard live in ~/.config/india-trade-lab/.
STORE="${ITL_CONFIG_DIR:-$HOME/.config/india-trade-lab}"
for file in "$HOME/.india-trade-lab.secrets" "$HOME/.india-trade-lab.env" \
            "$STORE/secrets.env" "$STORE/tokens.env"; do
  # shellcheck disable=SC1090
  [ -f "$file" ] && source "$file"
done

trading_day() {
  python3 - "$DATA/sessions.json" <<'PY'
import datetime as dt, json, sys
ist = dt.timezone(dt.timedelta(hours=5, minutes=30))
sessions = json.load(open(sys.argv[1]))["sessions"]
# A day listed as null (Muhurat, special sessions) is not traded by the desk.
sys.exit(0 if sessions.get(str(dt.datetime.now(ist).date())) else 1)
PY
}

job="${1:-}"
case "$job" in
  observatory)
    exec python3 scripts/observatory.py --data-dir "$DATA" ;;
  watchdog)
    # Every 2 minutes, every day: missed login, scan, report, worker, disk, backups.
    exec python3 scripts/watchdog.py --config "$CONFIG" check ;;
  backup)
    # Nightly, every day; the first of the month also proves the newest backup restores.
    python3 scripts/backup.py --config "$CONFIG" run
    if [ "$(date +%d)" = "01" ]; then
      python3 scripts/analytics.py --config "$CONFIG" report --period month --email || true
      exec python3 scripts/backup.py --config "$CONFIG" restore-test
    fi
    exit 0 ;;
esac

if ! trading_day; then
  echo "Not an NSE trading day in sessions.json; skipping $job."
  exit 0
fi

case "$job" in
  premarket)
    python3 scripts/reference.py --db "$DATA/reference.sqlite" refresh \
      || echo "NSE reference refresh failed; the report will use cached reference data."
    # With the market scan on: positioning, events and the overnight shortlist now;
    # the report itself is built at 09:09, after the pre-open auction.
    if python3 scripts/market_scan.py --config "$CONFIG" overnight; then
      python3 scripts/evidence.py collect --config "$CONFIG" --scan-shortlist \
        || echo "News collection failed; the report will use previously collected headlines."
    else
      echo "Market scan failed; the report will use the fixed stock list."
      python3 scripts/evidence.py collect --config "$CONFIG" \
        || echo "News collection failed; the report will use previously collected headlines."
    fi
    # NSE's official end-of-day file for the last sessions, then breadth, FII/DII and regime.
    python3 scripts/bhavcopy.py --config "$CONFIG" sync --days 5 \
      || echo "NSE bhavcopy not fetched; breadth will be missing from the market context."
    python3 scripts/market_context.py --config "$CONFIG" build \
      || echo "Market context not built; the agents work without it."
    exec python3 scripts/premarket.py --config "$CONFIG" --email --skip-when-scan ;;
  open)
    # 09:09: pre-open gap and strength against the Nifty, then the agents and judge.
    python3 scripts/market_scan.py --config "$CONFIG" open \
      || echo "Open scan failed; ranking on overnight signals only."
    exec python3 scripts/premarket.py --config "$CONFIG" --email ;;
  confirm)
    # 09:31: volume, VWAP and strength for the judge's picks; failures are not entered.
    exec python3 scripts/market_scan.py --config "$CONFIG" confirm ;;
  market)
    # A late start after a reboot is fine until 15:45; after that there is nothing to watch.
    now=$(TZ=Asia/Kolkata date +%H%M)
    if [ "$now" -ge 1545 ] || [ "$now" -lt 0900 ]; then
      echo "Outside market hours ($now IST); the worker starts at 09:05." && exit 0
    fi
    exec python3 scripts/market_service.py --config "$CONFIG" --refresh-india --prepare ;;
  aftermarket)
    # Keep sessions.json in step with the bundled NSE calendar (holidays, closing auction).
    python3 scripts/intraday.py --config "$CONFIG" sync-calendar \
      || echo "Calendar sync failed; sessions.json is unchanged."
    # Today's completed session into history, while today's Kite token is still valid,
    # then re-run the strategy tournament so tomorrow trades only what is still proven.
    python3 scripts/data_sync.py --config "$CONFIG" --days 90 --max-symbols 10 \
      || echo "History sync failed; the tournament will use the history already stored."
    # Performance page (both books), and on Fridays the week's results by email.
    python3 scripts/analytics.py --config "$CONFIG" report > /dev/null \
      || echo "Performance analytics not refreshed."
    if [ "$(date +%u)" = "5" ]; then
      python3 scripts/analytics.py --config "$CONFIG" report --period week --email || true
      mkdir -p "$DATA/reports"
      python3 scripts/itl.py --config "$CONFIG" track --days 7 \
        > "$DATA/reports/track-$(date +%F).md" || true
    fi
    python3 scripts/market_scan.py --config "$CONFIG" nightly \
      || echo "Daily candles for the scan were not refreshed; the morning scan will fetch them."
    # Swing desk: re-prove its setups on today's candles, then pick tomorrow's candidates.
    python3 scripts/swing.py --config "$CONFIG" tournament \
      || echo "Swing tournament did not run; yesterday's scorecard stays."
    python3 scripts/swing.py --config "$CONFIG" scan \
      || echo "Swing scan did not run; the swing desk will not enter tomorrow."
    python3 scripts/tournament.py --config "$CONFIG" \
      || echo "Tournament failed; yesterday's scorecard stays until it expires."
    # Grade every agent's calls on today's completed session and paper trades, and
    # write the lessons and stock notes tomorrow's agents will read.
    exec python3 scripts/learning.py --config "$CONFIG" settle ;;
  *)
    echo "Usage: run.sh premarket | open | confirm | market | aftermarket | watchdog | backup | observatory" >&2
    exit 64 ;;
esac
