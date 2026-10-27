# Backtest grid

Runs the real engine and journal across every complete broker-export session in
`history.sqlite`, with one continuous virtual book, the journal's own caps and
explicit costs. The same grid is then re-run with doubled costs. Offline, no
network, no orders.

```bash
python3 SKILL_DIR/scripts/backtest.py --history PROJECT/history.sqlite \
  --from 2026-05-01 --to 2026-10-24 --symbols NSE:INFY,NSE:TCS \
  --cash 100000 --risk 250 --daily-loss 750 --position-cap 15000 \
  --target-r 2 --fee-bps 5 --fee-flat 10 --slippage-bps 5 \
  --trades-csv PROJECT/backtest-trades.csv
```

Results are reported overall, per symbol, per month and for each half of the
period, so one lucky stretch is visible rather than averaged away. Reported
figures: trades, win rate, net INR, return, expectancy, average win and loss,
profit factor and maximum closed-trade drawdown.

## How to read it

The doubled-cost run matters more than the baseline. A rule whose edge disappears
when costs double has no margin for the spread, impact and partial fills that a
live book would meet. The grid models none of those: fills are assumed at the
bar's price with configured slippage, and there is no spread, depth, queue or
impact model.

Research-grid caps differ from forward practice on purpose. The loss-streak and
drawdown stops are lifted so a test period runs to its end; drawdown is measured
and reported instead. Per-trade risk, the daily planned-loss cap and the position
limit still apply, so sizing matches forward practice.

Tuning parameters until this sample looks good is overfitting. Choose the rule
and its settings on one period, then measure them once on a later period you have
not looked at. Past sessions are not evidence about future returns.
