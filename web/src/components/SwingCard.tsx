import { CalendarRange, CircleCheck, CircleSlash, Volume2 } from "lucide-react";
import type { SwingDesk } from "@/lib/types";
import { cn, dateTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/misc";
import { JobRunner } from "@/components/setup-kit";
import { SwingSimulator, inr, isOdds } from "@/components/SwingSimulator";

const SETUP: Record<string, string> = {
  "vol-breakout-v1": "Volume breakout",
  "pocket-pivot-v1": "Pocket pivot",
  "dryup-pullback-v1": "Dry-up pullback",
};

const rupee = (value: number | string | null | undefined) =>
  value == null || value === "" ? "—" : `₹${Number(value).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const signedRupees = (value: number) => `${value >= 0 ? "+" : "−"}₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;

/** Short swing trades on volume-confirmed daily setups, in their own ₹1 lakh paper book. */
export function SwingCard({ swing }: { swing: SwingDesk | null | undefined }) {
  const card = swing?.scorecard;
  const picks = swing?.candidates;
  return (
    <Card>
      <CardHeader className="flex-row items-start gap-4 space-y-0">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <CalendarRange className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <CardTitle>Swing desk</CardTitle>
          <CardDescription className="mt-1">
            Holds of up to 5 sessions, only when volume agrees with price: breakouts on 2x volume, pocket pivots and pullbacks on drying volume.
            Found after the close, entered after the next open, exited at the stop, the 2R target, a trailing stop or day 5. Its own paper book.
          </CardDescription>
        </div>
        {swing?.book && (
          <div className="num text-right text-sm">
            <p className="font-semibold">{rupee(swing.book.cash)}</p>
            <p className="text-xs text-muted-foreground">cash of {rupee(swing.book.initial_cash)}</p>
          </div>
        )}
      </CardHeader>
      <CardContent className="grid gap-6">
        <section className="grid gap-2" aria-labelledby="swing-proof">
          <h3 id="swing-proof" className="text-sm font-medium">Which setups have earned trading</h3>
          {card ? (
            <ul className="grid gap-2 sm:grid-cols-3">
              {Object.entries(card.strategies).map(([name, row]) => (
                <li key={name} className="rounded-lg border p-3 text-sm">
                  <p className="flex items-center gap-2 font-medium">
                    {row.eligible ? <CircleCheck className="size-4 text-success" /> : <CircleSlash className="size-4 text-muted-foreground" />}
                    {SETUP[name] ?? name}
                  </p>
                  <p className="num mt-1 text-xs text-muted-foreground">
                    {row.trades} {row.trades === 1 ? "trade" : "trades"} at double costs · {signedRupees(row.net_inr)}
                    {row.profit_factor != null && ` · PF ${row.profit_factor}`}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">{row.reason}</p>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No swing tournament yet. It runs after the close on the stored daily candles.</p>
          )}
          {card && <p className="text-xs text-muted-foreground">{card.sessions} sessions × {card.stocks} stocks · {dateTime(card.as_of)}</p>}
        </section>

        <section className="grid gap-2" aria-labelledby="swing-open">
          <h3 id="swing-open" className="text-sm font-medium">Open swing positions</h3>
          {swing?.positions.length ? (
            <Table>
              <thead>
                <tr><Th>Stock</Th><Th>Setup</Th><Th>Entry</Th><Th>Stop</Th><Th>Target</Th><Th>Held</Th></tr>
              </thead>
              <tbody>
                {swing.positions.map((row) => (
                  <tr key={row.symbol}>
                    <Td className="font-medium">{row.symbol.replace("NSE:", "")} <span className="num text-xs text-muted-foreground">×{row.qty}</span></Td>
                    <Td className="text-xs">{SETUP[row.strategy ?? ""] ?? row.strategy ?? "—"}</Td>
                    <Td className="num">{rupee(row.entry)}</Td>
                    <Td className="num">{rupee(row.stop)} {row.rule !== "initial" && <Badge variant="success" className="ml-1">{row.rule}</Badge>}</Td>
                    <Td className="num">{rupee(row.target)}</Td>
                    <Td className="num">{row.sessions_held} of 5</Td>
                  </tr>
                ))}
              </tbody>
            </Table>
          ) : (
            <p className="text-sm text-muted-foreground">{swing?.book ? "None open." : "Create the swing book in Setup → Create the paper book."}</p>
          )}
          {swing?.closed.length ? (
            <p className="num text-xs text-muted-foreground">
              Recent exits: {swing.closed.slice(-5).map((row) => `${row.symbol.replace("NSE:", "")} ${signedRupees(Number(row.net_inr ?? 0))}`).join(" · ")}
            </p>
          ) : null}
        </section>

        <section className="grid gap-2" aria-labelledby="swing-next">
          <h3 id="swing-next" className="flex items-center gap-2 text-sm font-medium">
            <Volume2 className="size-4" /> Candidates for the next session {picks && <span className="font-normal text-muted-foreground">· from the {picks.date} close, {picks.scanned} stocks</span>}
          </h3>
          {picks?.candidates.length ? (
            <ul className="grid gap-2">
              {picks.candidates.map((row) => (
                <li key={row.symbol} className={cn("grid gap-1 rounded-lg border p-3 text-sm", row.proven && "border-primary/40 bg-primary/5")}>
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{row.symbol.replace("NSE:", "")}</span>
                    <Badge variant={row.proven ? "solid" : "outline"}>{SETUP[row.strategy] ?? row.strategy}</Badge>
                    {row.vol_ratio != null && <Badge variant="outline">{row.vol_ratio}x volume</Badge>}
                    {row.obv_rising && <Badge variant="success">OBV rising</Badge>}
                    {!row.proven && <span className="text-xs text-muted-foreground">watch only: setup not proven</span>}
                  </p>
                  <p className="text-muted-foreground">{row.reason}</p>
                  <p className="num text-xs">Close {rupee(row.close)} · stop {rupee(row.stop)} ({row.risk_pct}%) · target {rupee(row.target)}</p>
                  {isOdds(row.odds) ? (
                    <p className="num text-xs">
                      Simulated: <span className={row.odds.expected_pnl_inr >= 0 ? "text-success" : "text-destructive"}>{inr(row.odds.expected_pnl_inr)} expected</span> ·{" "}
                      {row.odds.target_pct}% target · {row.odds.stopped_pct}% stopped · 1 in 20 worse than {inr(row.odds.p5_pnl_inr)}
                    </p>
                  ) : (
                    row.odds && "unavailable" in row.odds && <p className="text-xs text-muted-foreground">Simulation: {row.odds.unavailable}</p>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">{picks ? "No stock met a volume-confirmed setup at the last close." : "No swing scan yet."}</p>
          )}
          {picks?.notes.map((note) => <p key={note} className="text-xs text-warning">{note}</p>)}
          {picks && Object.keys(picks.skipped_for_events).length > 0 && (
            <p className="text-xs text-muted-foreground">Skipped for results or meetings in the holding period: {Object.keys(picks.skipped_for_events).map((s) => s.replace("NSE:", "")).join(", ")}</p>
          )}
        </section>

        <SwingSimulator candidates={picks?.candidates ?? []} />

        <div className="grid gap-3">
          <JobRunner kind="swing_tournament" label="Swing tournament" description="Replays each setup on the stored daily candles at double costs. Runs after the close." />
          <JobRunner kind="swing_scan" label="Swing scan" description="Finds candidates from the last close for the next session. Runs after the close." />
          <JobRunner kind="swing_tick" label="Enter and manage now" description="The session worker does this every tick: one entry pass after 09:15, then stops, targets and time exits." />
        </div>
      </CardContent>
    </Card>
  );
}
