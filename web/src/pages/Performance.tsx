import { useCallback } from "react";
import { get } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import { cn, dateTime, rupees, signed } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton, Table, Td, Th } from "@/components/ui/misc";

type Summary = {
  trades: number;
  net_inr: number;
  win_rate_pct: number | null;
  expectancy_inr: number | null;
  expectancy_r: number | null;
  profit_factor: number | null;
  average_win_inr: number | null;
  average_loss_inr: number | null;
  charges_inr: number;
};
type Performance = {
  as_of: string;
  summary: Summary;
  r_histogram: { from: number; to: number; count: number }[];
  excursions: { trades: number; average_mae_r: number | null; average_mfe_r: number | null; note: string };
  equity: { curve: { at: string; equity_inr: number; drawdown_inr: number }[]; max_drawdown_inr: number };
  attribution: Record<string, Record<string, Summary>>;
  drift: Record<string, { paper_trades: number; backtest_average_r: number; paper_average_r: number; cusum: number; alarm: boolean; verdict: string }>;
  tax: Record<string, { speculative_income_inr: number; speculative_tax_inr: number; stcg_inr: number; stcg_tax_inr: number; notes: string[] }>;
  recent: { symbol: string; book: string; net_inr: number; r: number | null; story: string; closed_at: string }[];
};
type Slippage = Record<string, { samples: number; configured_bps: number; median_bps?: number; p75_bps?: number; verdict: string }>;
type Health = {
  watchdog?: { last_check: string | null; problems: string[] };
  surveillance?: { checked_at: string | null; sources: Record<string, string>; blocked: string[]; caution: number };
  context?: {
    flows?: { fii_net_inr_crore?: number; dii_net_inr_crore?: number; date?: string };
    breadth?: { advances: number; declines: number; advance_decline_ratio: number | null } | null;
    regime?: { label: string; vix: number; nifty_vs_50d_pct: number };
    notes: string[];
  } | null;
  paused?: boolean;
  backup?: { latest: string | null; count: number };
  portfolio?: { capital_inr: number; open_risk_inr: number; heat_pct: number | null; max_heat_pct: number; by_sector: Record<string, number> };
  slippage?: Slippage;
  ai_spend?: { today_usd: number; month_usd: number; by_role: Record<string, { calls: number; usd: number }> };
};
type View = { performance: Performance | null; health: Health };

function Stat({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  return (
    <div className="rounded-lg border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={cn("num mt-1 text-lg font-semibold", tone === "good" && "text-success", tone === "bad" && "text-destructive")}>{value}</p>
    </div>
  );
}

function EquityChart({ curve }: { curve: Performance["equity"]["curve"] }) {
  if (curve.length < 2) return <p className="text-sm text-muted-foreground">The curve appears after two closed trades.</p>;
  const values = curve.map((point) => point.equity_inr);
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  const span = high - low || 1;
  const x = (index: number) => (index / (curve.length - 1)) * 100;
  const y = (value: number) => 40 - ((value - low) / span) * 36 - 2;
  const line = curve.map((point, index) => `${index ? "L" : "M"}${x(index).toFixed(2)},${y(point.equity_inr).toFixed(2)}`).join(" ");
  return (
    <figure>
      <svg viewBox="0 0 100 40" preserveAspectRatio="none" className="h-40 w-full" role="img" aria-label="Paper equity after each closed trade">
        <line x1="0" x2="100" y1={y(0)} y2={y(0)} className="stroke-border" strokeWidth="0.3" vectorEffect="non-scaling-stroke" />
        <path d={line} fill="none" className="stroke-primary" strokeWidth="2" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="num mt-1 flex justify-between text-xs text-muted-foreground">
        <span>{curve[0].at}</span>
        <span>{curve[curve.length - 1].at}</span>
      </figcaption>
    </figure>
  );
}

function Histogram({ buckets }: { buckets: Performance["r_histogram"] }) {
  const most = Math.max(1, ...buckets.map((bucket) => bucket.count));
  return (
    <div>
      <div className="flex h-28 items-end gap-0.5" role="img" aria-label="How many trades ended at each multiple of the risk">
        {buckets.map((bucket) => (
          <div
            key={bucket.from}
            title={`${bucket.from}R to ${bucket.to}R: ${bucket.count}`}
            className={cn("flex-1 rounded-t-sm", bucket.from < 0 ? "bg-destructive/60" : "bg-success/70")}
            style={{ height: `${(bucket.count / most) * 100}%`, minHeight: bucket.count ? 2 : 0 }}
          />
        ))}
      </div>
      <div className="num mt-1 flex justify-between text-xs text-muted-foreground">
        <span>{buckets[0]?.from}R</span>
        <span>0R</span>
        <span>{buckets[buckets.length - 1]?.to}R</span>
      </div>
    </div>
  );
}

function Breakdown({ title, rows }: { title: string; rows: Record<string, Summary> }) {
  const entries = Object.entries(rows);
  if (!entries.length) return null;
  return (
    <div className="min-w-0">
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      <Table>
        <thead>
          <tr>
            <Th>{title}</Th>
            <Th className="text-right">Trades</Th>
            <Th className="text-right">Win rate</Th>
            <Th className="text-right">Expectancy</Th>
            <Th className="text-right">Net</Th>
          </tr>
        </thead>
        <tbody>
          {entries.map(([key, row]) => (
            <tr key={key}>
              <Td>{key}</Td>
              <Td className="num text-right">{row.trades}</Td>
              <Td className="num text-right">{row.win_rate_pct ?? "—"}%</Td>
              <Td className="num text-right">{row.expectancy_r != null ? `${row.expectancy_r.toFixed(2)}R` : rupees(row.expectancy_inr)}</Td>
              <Td className={cn("num whitespace-nowrap text-right", row.net_inr >= 0 ? "text-success" : "text-destructive")}>{signed(row.net_inr)}</Td>
            </tr>
          ))}
        </tbody>
      </Table>
    </div>
  );
}

function HealthCard({ health }: { health: Health }) {
  const problems = health.watchdog?.problems ?? [];
  const heat = health.portfolio;
  const context = health.context;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Desk health</CardTitle>
        <CardDescription>
          The watchdog checks every 2 minutes. Last check {dateTime(health.watchdog?.last_check) || "not yet"}.
          {health.paused && " Entries are paused (HALT_ENTRIES); send /resume or delete the file."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 text-sm">
        {problems.length ? (
          <ul className="grid gap-1.5" aria-label="Open problems">
            {problems.map((text) => (
              <li key={text} className="rounded-md bg-destructive/10 px-3 py-2 text-destructive">
                {text}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-success">No problems found.</p>
        )}
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Open risk (both books)"
            value={heat?.heat_pct != null ? `${heat.heat_pct}% of ${rupees(heat.capital_inr)}` : "—"}
            tone={heat?.heat_pct != null && heat.heat_pct > heat.max_heat_pct ? "bad" : undefined}
          />
          <Stat label="Market regime" value={context?.regime?.label ?? "unknown"} />
          <Stat label="Surveillance blocks" value={health.surveillance?.checked_at ? `${health.surveillance.blocked.length} stocks` : "not read"} />
          <Stat label="AI spend this month" value={health.ai_spend ? `$${health.ai_spend.month_usd.toFixed(2)}` : "—"} />
        </div>
        {context && (
          <p className="text-muted-foreground">
            {context.flows?.fii_net_inr_crore != null && `FII net ₹${context.flows.fii_net_inr_crore.toLocaleString("en-IN")} cr, DII ₹${(context.flows.dii_net_inr_crore ?? 0).toLocaleString("en-IN")} cr. `}
            {context.breadth && `Breadth: ${context.breadth.advances} up, ${context.breadth.declines} down. `}
            {context.notes.join(". ")}
          </p>
        )}
        {health.slippage && (
          <div className="grid gap-1 text-muted-foreground">
            {Object.entries(health.slippage).map(([book, row]) => (
              <p key={book}>
                <span className="font-medium text-foreground">Slippage, {book}:</span> {row.samples} measured
                {row.p75_bps != null && `, 75% within ${row.p75_bps} bps (assumed ${row.configured_bps})`}. {row.verdict}.
              </p>
            ))}
          </div>
        )}
        <p className="text-muted-foreground">
          Backups: {health.backup?.latest ? `${health.backup.count} kept, newest ${health.backup.latest}` : "none yet (the nightly job makes them)"}.
        </p>
      </CardContent>
    </Card>
  );
}

export function PerformancePage() {
  const fetcher = useCallback(() => get<View>("/api/performance"), []);
  const { data } = usePoll(fetcher, 30_000);
  if (!data) return <Skeleton className="h-96" />;
  const view = data.performance;
  const total = view?.summary;
  return (
    <div className="grid min-w-0 gap-6 [&>*]:min-w-0">
      <HealthCard health={data.health} />
      {!view || !total || !total.trades ? (
        <Card>
          <CardHeader>
            <CardTitle>Performance</CardTitle>
            <CardDescription>
              No closed paper trades yet. This page fills in after the evening job (analytics.py report) once either book has closed a trade.
            </CardDescription>
          </CardHeader>
        </Card>
      ) : (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Results, both paper books</CardTitle>
              <CardDescription>Updated {dateTime(view.as_of)}. R is the result divided by the loss planned at entry. Paper only.</CardDescription>
            </CardHeader>
            <CardContent className="grid gap-5">
              <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
                <Stat label="Net after charges" value={signed(total.net_inr)} tone={total.net_inr >= 0 ? "good" : "bad"} />
                <Stat label="Trades" value={String(total.trades)} />
                <Stat label="Win rate" value={`${total.win_rate_pct ?? "—"}%`} />
                <Stat label="Expectancy" value={total.expectancy_r != null ? `${total.expectancy_r.toFixed(2)}R` : rupees(total.expectancy_inr)} />
                <Stat label="Profit factor" value={total.profit_factor != null ? total.profit_factor.toFixed(2) : "—"} />
                <Stat label="Deepest drawdown" value={rupees(view.equity.max_drawdown_inr)} />
              </div>
              <div className="grid gap-6 lg:grid-cols-2">
                <div>
                  <h3 className="mb-2 text-sm font-medium">Equity after each trade</h3>
                  <EquityChart curve={view.equity.curve} />
                </div>
                <div>
                  <h3 className="mb-2 text-sm font-medium">Trades by result (R)</h3>
                  <Histogram buckets={view.r_histogram} />
                  {view.excursions.trades > 0 && (
                    <p className="num mt-2 text-xs text-muted-foreground">
                      Swing trades went {view.excursions.average_mae_r}R against and {view.excursions.average_mfe_r}R in favour on average while held.
                    </p>
                  )}
                </div>
              </div>
              <p className="text-xs text-muted-foreground">Charges paid: {rupees(total.charges_inr, true)}.</p>
            </CardContent>
          </Card>
          {Object.keys(view.drift).length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Paper against the backtest</CardTitle>
                <CardDescription>A running check (CUSUM) that alarms when paper results keep falling short of the tournament.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-2 text-sm">
                {Object.entries(view.drift).map(([key, row]) => (
                  <p key={key} className="flex flex-wrap items-center gap-2">
                    <Badge variant={row.alarm ? "destructive" : "success"}>{row.alarm ? "Drifting" : "In line"}</Badge>
                    <span className="font-medium">{key}</span>
                    <span className="num text-muted-foreground">
                      paper {row.paper_average_r}R over {row.paper_trades} trades, backtest {row.backtest_average_r}R
                    </span>
                  </p>
                ))}
              </CardContent>
            </Card>
          )}
          <Card>
            <CardHeader>
              <CardTitle>Where the results came from</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-6 lg:grid-cols-2">
              <Breakdown title="Strategy" rows={view.attribution.strategy ?? {}} />
              <Breakdown title="Market regime" rows={view.attribution.regime ?? {}} />
              <Breakdown title="Weekday" rows={view.attribution.weekday ?? {}} />
              <Breakdown title="Entry hour" rows={view.attribution.entry_hour ?? {}} />
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Recent trades, explained</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="grid gap-3 text-sm">
                {view.recent.map((trade) => (
                  <li key={`${trade.symbol}-${trade.closed_at}`} className="rounded-lg border p-3">
                    {trade.story}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Tax view (estimate)</CardTitle>
              <CardDescription>Not tax advice. Paper trades are not taxable; this shows what the same results would roughly owe.</CardDescription>
            </CardHeader>
            <CardContent>
              <Table>
                <thead>
                  <tr>
                    <Th>Year</Th>
                    <Th className="text-right">Intraday (speculative)</Th>
                    <Th className="text-right">Tax</Th>
                    <Th className="text-right">Swing (STCG)</Th>
                    <Th className="text-right">Tax</Th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(view.tax).map(([year, row]) => (
                    <tr key={year}>
                      <Td>{year}</Td>
                      <Td className="num whitespace-nowrap text-right">{signed(row.speculative_income_inr)}</Td>
                      <Td className="num text-right">{rupees(row.speculative_tax_inr)}</Td>
                      <Td className="num whitespace-nowrap text-right">{signed(row.stcg_inr)}</Td>
                      <Td className="num text-right">{rupees(row.stcg_tax_inr)}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
              <ul className="mt-3 list-disc pl-5 text-xs text-muted-foreground">
                {(Object.values(view.tax)[0]?.notes ?? []).map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
