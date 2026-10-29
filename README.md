# India Trade Lab

**An AI research desk for NSE stocks that trades a virtual book, and sits out when nothing has earned the right to trade.**

Every morning, specialist agents read the news, charts, sectors and broker calls for your stocks, and a judge picks up to three to watch. During the session, only strategies that proved themselves on your own history trade them, in a paper book with hard loss limits. Every evening, each agent is graded and learns from its mistakes.

Paper only: there is no real-order path. Nothing here is a promise of profit.

![The India Trade Lab dashboard](docs/images/dashboard.png)

## Try it in 2 minutes

```bash
git clone https://github.com/kaifiasif/india-trade-lab.git && cd india-trade-lab
python3 scripts/observatory.py    # open http://127.0.0.1:8765, then Paper replay → Start replay
```

Needs only Python 3.10 or newer. The replay uses a bundled made-up session. To
see what the morning report looks like, open the
[sample report](docs/examples/premarket-sample.html). To meet the agents, read the
[Meet the Desk guide](docs/guide/agents-guide.pdf).

## Use it with real data

Set it up once from the dashboard's **Setup** page, which takes about an hour.
You add your Kite Connect keys, an email app password, an optional AI model key,
your stocks and 180 days of history. Keys are kept in a private file on the
server and never shown again.

To run it every day for free, follow [Deploy on Oracle Cloud](docs/deploy-oracle.md).
After that, each morning takes about two minutes: the Kite login and two checks,
from your phone.

**Costs:**

- Kite Connect: ₹500 a month.
- Oracle Cloud hosting: ₹0.
- AI agents: ₹0 on Gemini's free tier.

## A trading day

| When (IST) | What happens |
|---|---|
| 08:30 | You log in to Kite |
| 08:40 | Code scans every F&O stock: futures positioning, delivery, large deals, upcoming events |
| 09:09 | Pre-open gap against the Nifty; agents and the judge pick from the best ten; picks are emailed |
| 09:15–15:15 | Picks that pass the 09:31 volume and VWAP check are traded in the paper book; code sizes every trade |
| 15:15 | Everything is squared off |
| 16:10 | History is saved, strategies are re-tested at double costs, and agents are graded |

If no strategy has made money at double costs on your history, the desk sits
out and records no trades. That is the safe outcome, not a fault.

## What it does

- **Market scan:** the desk picks its own stocks from every F&O name, on signals that lead the open, not only yesterday's news. See [market-scan.md](skills/day-trader-india/references/market-scan.md).
- **Pre-market report:** trend, RSI, sector moves, liquidity, headline sentiment and broker calls for each stock.
- **Agents:** six specialists, a risk scout, a setup planner and a judge. Agents can only narrow or veto; code decides size.
- **Strategies:** an opening-range breakout and a VWAP pullback, with breakeven, trailing and time stops.
- **Learning:** mistakes become lessons the agents read next morning, and stocks that keep losing sit out for a week.
- **Smart model routing:** simple jobs go to a free tier, so free quotas last.
- **Dashboard:** setup, today's picks, replays, research and each agent's track record, in light and dark.

## What it does not do

- **Place real orders.** Real trading would need new code and your explicit decision.
- **Log in to Kite for you.** Kite requires a daily 2FA login.
- **Guarantee profit.** Past sessions do not predict future returns.

## Documentation

- [Dashboard and setup](docs/observatory.md)
- [Deploy on Oracle Cloud](docs/deploy-oracle.md) · [Run on your own computer](docs/live-data.md)
- [Pre-market report](skills/day-trader-india/references/premarket.md) · [Strategies and tournament](skills/day-trader-india/references/strategy.md) · [Learning and routing](skills/day-trader-india/references/learning.md)
- [Paper engine](skills/day-trader-india/references/engine.md) · [Guardrails](skills/day-trader-india/references/guardrails.md) · [Command-line tools](skills/day-trader-india/references/data-and-tools.md)
- [Install as skills for Claude, Codex and other agents](docs/installation.md)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). `python3 scripts/check.py` runs the lint, tests and skill checks.

## Licence

MIT. See [LICENSE](LICENSE).
