# Run India Trade Lab on Oracle Cloud (free, no Mac needed)

This runs the whole paper-research desk on an Oracle Cloud **Always Free** server
in Mumbai. You manage it from a browser and a phone SSH app. Nothing here places
a real order: it is paper research only.

Running cost: the server is ₹0. Kite Connect, which provides the market data, is
₹500 per month. The research model is ₹0 on Gemini's free tier, or about ₹70 per
month with Claude.

## What runs, and when (IST, NSE trading days only)

| Time | Job | Needs today's Kite login |
|---|---|---|
| 08:40 | NSE reference refresh, news collection (Google News, NSE filings, ET Markets), pre-market report emailed to you | No |
| 09:05–15:50 | Research worker: live Kite quotes and candles, agent reviews and debates; with the autopilot on, it records approved paper entries and exits itself | Yes |
| 16:10 | Today's completed session saved into history, the strategy tournament re-run, then every agent graded on the day so tomorrow's agents read their lessons | Yes |
| Always | Dashboard on the server's loopback, reached through an SSH tunnel | No |

Jobs skip themselves on days that are not in `sessions.json`.

## 1. Create the Oracle account

1. Go to [oracle.com/cloud/free](https://www.oracle.com/cloud/free/) and sign up.
   Oracle asks for a card to verify you; the Always Free resources are not charged.
2. Choose **India West (Mumbai)** as the home region. You cannot change the home
   region later, and Always Free servers can only be created there.

## 2. Create the server

1. In the console: **Compute → Instances → Create instance**.
2. **Image:** Canonical Ubuntu 24.04.
3. **Shape:** Ampere `VM.Standard.A1.Flex` with 2 OCPU and 12 GB memory. If it
   reports "Out of host capacity", try again later, or use the AMD
   `VM.Standard.E2.1.Micro` (1 GB), which also works for this.
4. **Networking:** keep the default network and **assign a public IPv4 address**.
5. **SSH keys:** choose **Generate a key pair** and download the private key. Keep
   it safe; it is the only way in.
6. Click **Create** and note the public IP address.

Optional: under **Networking → Reserved public IPs**, reserve the address so it
never changes. SEBI's algo rules require a registered static IP if real orders are
ever placed through an API. This project does not place real orders, so reserving
the IP is only preparation for later.

Do **not** open any port other than SSH (22). The dashboard is reached through SSH.

## 3. Connect

From a laptop:

```bash
chmod 600 ~/Downloads/ssh-key.key
ssh -i ~/Downloads/ssh-key.key ubuntu@YOUR_SERVER_IP
```

From a phone: install **Termius** (iOS or Android). Add a host with the IP, the
username `ubuntu` and the downloaded key.

## 4. Install

```bash
git clone https://github.com/kaifiasif/india-trade-lab.git ~/india-trade-lab
bash ~/india-trade-lab/deploy/oracle/setup.sh
```

The setup script does the following:
- Sets the clock to IST.
- Creates `~/india-trade-lab/data/observatory` with the NSE 2026 calendar.
- Creates the owner-only `~/.india-trade-lab.secrets` file.
- Installs the scheduled jobs.

You can run it again safely.

## 5. Open the dashboard and finish Setup

The dashboard is on the server's loopback only and is never exposed to the
internet. Open it through an SSH tunnel:

```bash
ssh -i ~/Downloads/ssh-key.key -L 8765:127.0.0.1:8765 ubuntu@YOUR_SERVER_IP
```

Then open <http://127.0.0.1:8765> on the same device. On a phone, add a local
port forward from 8765 to 127.0.0.1:8765 in Termius and open that address in the
phone browser.

Go to **Setup** and work down the eleven steps. Everything the old command-line
steps did is there:

- **Your details**: your name and where the morning report goes.
- **Kite Connect keys**: the API key and secret from
  [developers.kite.trade](https://developers.kite.trade).
- **Today's Kite login**: open Zerodha's login, finish 2FA, then paste back the
  address the browser lands on (`http://127.0.0.1/?...request_token=...`; that
  page itself will not load, which is expected).
- **Email delivery**: pick Gmail (or another service), enter your address and a
  16-character Gmail **app password** (needs 2-Step Verification), then press
  *Send a test email*.
- **Research model**: optional. Pick a provider, paste its key and the exact
  model ID (for Gemini's free tier, copy it from Google AI Studio).
  Turn on **Smart routing** there to send the simple jobs to a free tier and only
  the judge to a stronger one, with the daily limits your key shows.
- **Choose stocks**: upload NSE's `EQUITY_L.csv` (download it from nseindia.com on
  your phone if needed), search, and pick one to three stocks.
- **Load history**, **Run the tournament**, **Create the paper book** and
  **Today's checks** (where you checked the ASM/GSM lists and announcements).

Keys and passwords are written to `~/.config/india-trade-lab/` (owner-only) and
never to `pipeline.json`; the page shows only "saved, ends 1234". The scheduled
jobs read them from there. Other settings, such as the autopilot, model budget
and costs, are under **Settings**.

To let the agents trade the paper book on their own all session, turn on
**Settings → Strategies → Autopilot**. Each tick, it records the coordinator's
approved entry, but only for a stock the pre-market judge picked today. It also
records every protective exit: stop, target, and the 15:15 square-off. Every
journal limit still applies: per-trade risk, daily loss, trade count, open
positions, loss streak and drawdown stop. It uses virtual money only. To stop new
entries at once, create `data/observatory/HALT_ENTRIES`; exits keep running.

The tournament reports which strategies are eligible. If none are, the desk
sits out until one proves itself (see
[strategy.md](../skills/day-trader-india/references/strategy.md)). The stock list
expires after 30 days, so rebuild it monthly.

The command-line route still works (`deploy/oracle/login.sh`, then
`scripts/make_universe.py`, `data_sync.py` and `tournament.py`) if you prefer it.

## 6. Every trading morning (about 2 minutes, from the phone)

Before 09:05, open the dashboard through the tunnel and do **Setup → Today's
Kite login**, then **Today's checks**. Kite requires this daily login; it cannot
be automated around. Entries stay blocked until both checks are answered. The
pre-market report also arrives by email each morning, and copies are kept in
`data/observatory/reports/`.

## Check on it

```bash
python3 ~/india-trade-lab/scripts/itl.py --config ~/india-trade-lab/data/observatory/pipeline.json status
systemctl list-timers 'india-trade-lab*'
journalctl -u india-trade-lab-premarket -n 50
journalctl -u india-trade-lab-market -f
~/india-trade-lab/deploy/oracle/run.sh premarket   # run the report now (trading days)
```

Update to the latest code with `cd ~/india-trade-lab && git pull`.
