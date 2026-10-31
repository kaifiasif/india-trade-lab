# Before any real money: a checklist

India Trade Lab is a paper research desk. It has no code that places an order, and
none should be added casually. This page lists what would have to be true before
you even consider real trading, so the decision is made on evidence, not on a good
week.

## 1. The evidence

- [ ] At least **100 closed paper trades per strategy** (both books), over at
      least **three months** that include more than one market regime.
- [ ] Paper expectancy is **positive after charges**, and the Performance page
      shows **no drift alarm** for the strategy you would trade.
- [ ] The tournament still lists the strategy as eligible: it beats **95% of
      random-entry twins** and its **Deflated Sharpe is at least 0.95**.
- [ ] Shadow fills show measured slippage **within** the configured
      `slippage_bps` at the 75th percentile.
- [ ] The deepest paper drawdown is a loss you could take in real money without
      changing your behaviour.

If any box is unticked, keep paper trading. Most retail intraday traders lose
money: SEBI's 2024 study found that over 70% of individual intraday traders in
the equity cash segment made net losses in FY23.

## 2. The rules that would apply

- **SEBI's retail algorithmic trading framework** (in force from 1 April 2026):
  orders from an automated program must go through your broker's registered
  arrangement, from a **static IP** registered with the broker, and a strategy
  sending orders above the exchange's orders-per-second threshold must be
  registered with the exchange through the broker. Read your broker's current
  rules and the SEBI circular before writing any order code.
- Kite requires a **daily manual login** (2FA). Automating it breaks Zerodha's
  terms; this project will not do it.
- **Tax**: intraday profit is speculative business income at your slab rate;
  short-term delivery gains are taxed at 20% under section 111A. Speak to a tax
  professional.

## 3. The engineering that does not exist yet

Real orders would need, at minimum: order placement with idempotent client IDs,
handling of partial fills and rejections, broker-side stop-loss orders (so a
crash cannot leave a position unprotected), reconciliation of the broker's
positions against the journal every minute, a hard daily loss stop enforced at
the broker, a kill switch, and weeks of running that code against the paper book
side by side. None of it is written, on purpose.

## 4. The decision

Real trading is your decision alone, with your own money and your own risk. This
project and its agents give research, not financial advice.
