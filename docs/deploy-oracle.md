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
| 09:05–15:50 | Research worker: live Kite quotes and candles, agent reviews and debates, paper proposals | Yes |
| 16:10 | Today's completed session saved into history | Yes |
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

## 5. Add your keys and settings

```bash
nano ~/.india-trade-lab.secrets
```

Fill in `KITE_API_KEY` and `KITE_API_SECRET` from
[developers.kite.trade](https://developers.kite.trade). Fill in `SMTP_PASSWORD`:
a Gmail **app password**, which needs 2-Step Verification on your Google account.
Optionally, add one model key. Never paste this file into chat or Git.

Then edit `~/india-trade-lab/data/observatory/pipeline.json`:

```json
"smtp_host": "smtp.gmail.com",
"smtp_port": 587,
"smtp_user": "you@gmail.com",
"email_to": "you@gmail.com",
"max_model_calls_per_day": 20,
"max_output_tokens": 2500
```

To let the specialist agents and the judge run, set a provider and models. With
Gemini's free tier, copy the exact model IDs shown in Google AI Studio:

```json
"model_provider": "gemini",
"quick_model": "<Flash model id from AI Studio>",
"deep_model": "<Flash model id from AI Studio>"
```

Leave `model_provider` as `disabled` until the key is in the secrets file;
otherwise the run stops and reports the missing key.

## 6. First day: log in, choose stocks, load history

```bash
~/india-trade-lab/deploy/oracle/login.sh
source ~/.india-trade-lab.env
cd ~/india-trade-lab
curl -fsSL -A "Mozilla/5.0" -o ~/EQUITY_L.csv \
  https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv
python3 scripts/make_universe.py --equity-list ~/EQUITY_L.csv \
  --symbols INFY,TCS,RELIANCE --output data/observatory/universe.json
python3 scripts/data_sync.py --config data/observatory/pipeline.json --days 180 --max-symbols 3
python3 scripts/preflight.py --config data/observatory/pipeline.json
```

The symbols are examples, not recommendations. If NSE refuses the `curl` from a
cloud server, download `EQUITY_L.csv` on your phone and upload it to `~/` with
Termius's SFTP. The stock list expires after 30 days, so rebuild it monthly.

## 7. Every trading morning (about 2 minutes, from the phone)

Before 09:05:

```bash
~/india-trade-lab/deploy/oracle/login.sh
```

The script prints Zerodha's login link. Log in with 2FA, then paste back the
address the browser lands on (`http://127.0.0.1/?...request_token=...`; the page
itself will not load, which is expected). It saves today's token and restarts the
research worker. Kite requires this daily login; it cannot be automated around.

## The dashboard (UI)

The dashboard is on the server's loopback only. It is never exposed to the
internet. Open it through an SSH tunnel:

```bash
ssh -i ~/Downloads/ssh-key.key -L 8765:127.0.0.1:8765 ubuntu@YOUR_SERVER_IP
```

Then open <http://127.0.0.1:8765> on the same device. In Termius, add a local
port forward from 8765 to 127.0.0.1:8765 and open that address in the phone
browser. The pre-market report also arrives by email each morning, and copies
are kept in `data/observatory/reports/`.

## Check on it

```bash
systemctl list-timers 'india-trade-lab*'
journalctl -u india-trade-lab-premarket -n 50
journalctl -u india-trade-lab-market -f
~/india-trade-lab/deploy/oracle/run.sh premarket   # run the report now (trading days)
```

Update to the latest code with `cd ~/india-trade-lab && git pull`.
