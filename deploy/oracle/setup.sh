#!/usr/bin/env bash
# One-time setup of India Trade Lab on an Oracle Cloud Always Free Ubuntu server.
# Run as the default "ubuntu" user:  bash ~/india-trade-lab/deploy/oracle/setup.sh
# Safe to re-run. Paper research only: nothing here places an order.
set -euo pipefail

REPO="$HOME/india-trade-lab"
DATA="$REPO/data/observatory"
USER_NAME="$(id -un)"
SECRETS="$HOME/.india-trade-lab.secrets"

echo "== Packages and IST clock"
sudo apt-get update -qq
sudo apt-get install -y -qq git python3 sqlite3 >/dev/null
sudo timedatectl set-timezone Asia/Kolkata
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10+ is required"'

echo "== Repository"
if [ ! -d "$REPO/.git" ]; then
  git clone https://github.com/kaifiasif/india-trade-lab.git "$REPO"
fi
chmod +x "$REPO/deploy/oracle/"*.sh

echo "== Private project folder"
mkdir -p "$DATA"
if [ ! -f "$DATA/pipeline.json" ]; then
  (cd "$REPO" && python3 scripts/decision_pipeline.py init --config "$DATA/pipeline.json")
fi
[ -f "$DATA/sessions.json" ] || cp "$REPO/skills/day-trader-india/assets/nse-sessions-2026.json" \
  "$DATA/sessions.json"

echo "== Secrets file (owner-only)"
if [ ! -f "$SECRETS" ]; then
  umask 077
  cat >"$SECRETS" <<'ENV'
# Private. Never commit or paste this file anywhere.
export KITE_API_KEY=
export KITE_API_SECRET=
# Gmail app password for the pre-market email.
export SMTP_PASSWORD=
# One research model key (leave empty to use the deterministic ranking).
export GEMINI_API_KEY=
export ANTHROPIC_API_KEY=
ENV
fi
chmod 600 "$SECRETS"

echo "== systemd units"
unit() { sudo tee "/etc/systemd/system/$1" >/dev/null; }
common="User=$USER_NAME
WorkingDirectory=$REPO
Environment=PYTHONDONTWRITEBYTECODE=1
UMask=0077
NoNewPrivileges=true
PrivateTmp=true"

unit india-trade-lab-premarket.service <<UNIT
[Unit]
Description=India Trade Lab pre-market report and email
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
$common
ExecStart=$REPO/deploy/oracle/run.sh premarket
UNIT

unit india-trade-lab-premarket.timer <<'UNIT'
[Unit]
Description=Overnight scan and news at 08:40 IST on weekdays
[Timer]
OnCalendar=Mon..Fri *-*-* 08:40:00
Persistent=false
[Install]
WantedBy=timers.target
UNIT

for stage in open confirm; do
  case "$stage" in
    open) when="09:09:30"; what="Open scan, agents and judge after the pre-open auction" ;;
    confirm) when="09:31:00"; what="Volume and VWAP check of the judge's picks" ;;
  esac
  unit "india-trade-lab-$stage.service" <<UNIT
[Unit]
Description=India Trade Lab: $what
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
$common
ExecStart=$REPO/deploy/oracle/run.sh $stage
UNIT
  unit "india-trade-lab-$stage.timer" <<UNIT
[Unit]
Description=$what at $when IST on weekdays
[Timer]
OnCalendar=Mon..Fri *-*-* $when
Persistent=false
[Install]
WantedBy=timers.target
UNIT
done

unit india-trade-lab-market.service <<UNIT
[Unit]
Description=India Trade Lab paper research worker (market hours)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
$common
ExecStart=$REPO/deploy/oracle/run.sh market
Restart=on-failure
RestartSec=120
RuntimeMaxSec=24300
UNIT

unit india-trade-lab-market.timer <<'UNIT'
[Unit]
Description=Start the research worker at 09:05 IST on weekdays (stops itself by 15:50)
[Timer]
OnCalendar=Mon..Fri *-*-* 09:05:00
# After a reboot during market hours, start at once: the worker recovers open paper
# positions and squares off anything overdue on its first tick.
Persistent=true
[Install]
WantedBy=timers.target
UNIT

unit india-trade-lab-aftermarket.service <<UNIT
[Unit]
Description=India Trade Lab history sync after the close
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
$common
ExecStart=$REPO/deploy/oracle/run.sh aftermarket
UNIT

unit india-trade-lab-aftermarket.timer <<'UNIT'
[Unit]
Description=History sync at 16:10 IST on weekdays
[Timer]
OnCalendar=Mon..Fri *-*-* 16:10:00
Persistent=false
[Install]
WantedBy=timers.target
UNIT

unit india-trade-lab-observatory.service <<UNIT
[Unit]
Description=India Trade Lab dashboard on 127.0.0.1:8765 (reach it through an SSH tunnel)
After=network-online.target
[Service]
Type=simple
$common
ExecStart=$REPO/deploy/oracle/run.sh observatory
Restart=on-failure
RestartSec=30
[Install]
WantedBy=multi-user.target
UNIT

# Let the daily login restart only the market service, without a password prompt.
echo "$USER_NAME ALL=(root) NOPASSWD: /usr/bin/systemctl restart india-trade-lab-market.service" |
  sudo tee /etc/sudoers.d/india-trade-lab >/dev/null
sudo chmod 440 /etc/sudoers.d/india-trade-lab
sudo visudo -cf /etc/sudoers.d/india-trade-lab >/dev/null

sudo systemctl daemon-reload
sudo systemctl enable --now india-trade-lab-premarket.timer india-trade-lab-open.timer \
  india-trade-lab-confirm.timer india-trade-lab-market.timer \
  india-trade-lab-aftermarket.timer india-trade-lab-observatory.service

cat <<DONE

Setup complete. Next:
  1. nano $SECRETS                      # fill in your keys
  2. nano $DATA/pipeline.json           # email and model settings (see docs/deploy-oracle.md)
  3. ~/india-trade-lab/deploy/oracle/login.sh   # today's Kite login
  4. Build the stock list and history once (docs/deploy-oracle.md, step 6)
Scheduled jobs:  systemctl list-timers 'india-trade-lab*'
Logs:            journalctl -u india-trade-lab-premarket -n 50
DONE
