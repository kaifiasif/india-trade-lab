# What to use from the two source projects

Reviewed 21 October 2026. These links explain the design influences. Do not
auto-update the installed US source skills or overwrite one with another:
the projects reuse several skill names but implement different workflows.

- Day trading project: https://github.com/Jakeschincariol/day-trader-skill
  Source pinned in `upstream-integrity.json` for the separately installed tools.
- Portfolio project: https://github.com/Jakeschincariol/trader-skill
  README SHA at review: `449cb93a62fb072cb01b9bbb454197edc30f39a0`.

| Source idea | Indian implementation or treatment |
| --- | --- |
| Scan, entry, stop, time exit | Standalone India five-minute CSV scanner and explicit session manifests; historical replay with next-bar entry and costs. |
| Budget and risk checks | INR virtual-cash journal with planned risk, daily budget, cash/position caps, daily entry/open-position caps, loss-streak/drawdown stops and pause. |
| Monte Carlo Time Machine | The US code remains US-specific. No India Monte Carlo model is claimed. Prefer inspectable out-of-sample historical/forward evidence before adding one. |
| Fundamental screener | India point-in-time CSV rules with source/publication dates; missing and future data fail. |
| Earnings/news | NSE/BSE announcements and company IR sources. Fetch/review these separately; the toolkit does not scrape them automatically. |
| Portfolio rebalancing | Guided, read-only concentration/drift review using the user's real holdings and dated prices. No automatic rebalance orders or executable rebalance tool is claimed. |
| 13F investor copycat | Replace with dated NSE/BSE shareholding patterns or AMC/AMFI portfolio disclosures for research. These are partial snapshots with publication lags, not live investor trade alerts or a matching 13F dataset. |
| US congressional/Pelosi tracker | Omit from India decision workflow. No asserted Indian equivalent. |
| US tax lots/wash sales | Do not port as Indian tax rules. Keep dated transactions, quantities, fees and cost-basis evidence for later India-specific analysis; verify current law separately. |
| Alpaca/IBKR execution | No live Indian execution. Read-only Kite/Upstox historical data adapters plus a manual virtual journal; OpenAlgo Analyzer is an optional later adapter. |

India-specific disclosure sources:

- NSE shareholding patterns: https://www.nseindia.com/companies-listing/corporate-filings-shareholding-pattern
- BSE shareholding search: https://www.bseindia.com/corporates/Sharehold_Searchnew.aspx
- AMFI portfolio disclosures: https://www.amfiindia.com/online-center/portfolio-disclosure
- NSE corporate information: https://www.nseindia.com/companies-listing/corporate-filings-application

Changes in published holdings do not identify a trade date, exact execution
price, the full portfolio, or the investor's present position. Do not infer
future returns from an institutional name or automatically copy its holdings.
