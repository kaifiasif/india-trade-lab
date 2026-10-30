import { BellRing, Clock3, Crosshair, ShieldCheck, ShieldX, Timer } from "lucide-react";
import type { DeskCard, FanPoint, TradeDesk } from "@/lib/types";
import { cn, dateTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { JobRunner } from "@/components/setup-kit";

const STATUS: Record<string, { label: string; tone: "success" | "warning" | "destructive" | "outline" | "default" }> = {
  TRIGGERED: { label: "Triggered", tone: "success" },
  WAITING: { label: "Waiting", tone: "default" },
  FORMING: { label: "Range forming", tone: "outline" },
  NOT_OPEN: { label: "Not open", tone: "outline" },
  EXPIRED: { label: "Expired", tone: "outline" },
  CLOSED: { label: "Market closed", tone: "outline" },
  DATA_BLOCK: { label: "No data", tone: "warning" },
};

const LEAN: Record<string, "success" | "warning" | "destructive" | "outline"> = {
  strong_target: "success",
  lean_target: "success",
  coin_flip: "outline",
  break_even: "outline",
  undecided: "outline",
  lean_stop: "warning",
  strong_stop: "destructive",
};

const rupee = (value: number) => `₹${value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** Where the replayed price sits bar by bar: 90% band, middle half and the median. */
function Fan({ fan, entry, stop, target }: { fan: FanPoint[]; entry: number; stop: number; target: number }) {
  if (fan.length < 2) return null;
  const width = 320;
  const height = 120;
  const low = Math.min(stop, ...fan.map((point) => point.p5));
  const high = Math.max(target, ...fan.map((point) => point.p95));
  const span = high - low || 1;
  const x = (index: number) => (index / (fan.length - 1)) * width;
  const y = (price: number) => height - 6 - ((price - low) / span) * (height - 12);
  const band = (top: keyof FanPoint, bottom: keyof FanPoint) =>
    fan.map((point, index) => `${x(index)},${y(point[top])}`).join(" ") +
    " " +
    [...fan].reverse().map((point, index) => `${x(fan.length - 1 - index)},${y(point[bottom])}`).join(" ");
  const line = (price: number) => <line x1={0} x2={width} y1={y(price)} y2={y(price)} strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />;
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-28 w-full" role="img" aria-label="Spread of replayed prices until the square-off">
      <polygon points={band("p95", "p5")} className="fill-primary/10" />
      <polygon points={band("p75", "p25")} className="fill-primary/20" />
      <polyline points={fan.map((point, index) => `${x(index)},${y(point.p50)}`).join(" ")} className="fill-none stroke-primary" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      <g className="stroke-success">{line(target)}</g>
      <g className="stroke-muted-foreground">{line(entry)}</g>
      <g className="stroke-destructive">{line(stop)}</g>
    </svg>
  );
}

function Odds({ card }: { card: DeskCard }) {
  const odds = card.odds!;
  const parts = [
    { label: "target first", value: odds.target_first_pct, className: "bg-success" },
    { label: "neither", value: odds.neither_pct, className: "bg-muted-foreground/40" },
    { label: "stop first", value: odds.stop_first_pct, className: "bg-destructive" },
  ];
  return (
    <div className="grid gap-2">
      <div className="flex h-2.5 overflow-hidden rounded-full" aria-hidden>
        {parts.map((part) => (
          <div key={part.label} className={part.className} style={{ width: `${part.value}%` }} />
        ))}
      </div>
      <p className="num text-xs text-muted-foreground">
        {parts.map((part) => `${part.value}% ${part.label}`).join(" · ")} · {odds.replays.toLocaleString("en-IN")} replays from {odds.sessions} sessions, seed {odds.seed}
      </p>
      {card.plan && odds.fan && <Fan fan={odds.fan} entry={card.plan.entry} stop={card.plan.stop} target={card.plan.target} />}
      <p className="text-sm">
        <Badge variant={LEAN[odds.code] ?? "outline"} className="mr-2">
          {odds.code.replace("_", " ")}
        </Badge>
        {odds.verdict}
      </p>
      <p className="num text-xs text-muted-foreground">
        Average R {odds.average_r >= 0 ? "+" : ""}
        {odds.average_r.toFixed(3)}
        {odds.after_costs != null && `, after costs ${odds.after_costs >= 0 ? "+" : ""}${odds.after_costs.toFixed(3)}`}
        {odds.history && ` · history: fired ${odds.history.fired} times, ${odds.history.target} target, ${odds.history.stop} stop`}
      </p>
    </div>
  );
}

function PickCard({ card }: { card: DeskCard }) {
  const status = STATUS[card.entry.status ?? ""] ?? { label: card.entry.status ?? "—", tone: "outline" as const };
  return (
    <article className="grid min-w-0 gap-3 rounded-lg border p-4">
      <header className="flex items-center justify-between gap-2">
        <h3 className="font-semibold">{card.symbol.replace("NSE:", "")}</h3>
        <Badge variant={status.tone}>{status.label}</Badge>
      </header>
      <p className="text-sm text-muted-foreground">{card.entry.message}</p>
      {card.plan && (
        <dl className="num grid grid-cols-3 gap-2 text-sm">
          {[
            ["Entry", card.plan.entry],
            ["Stop", card.plan.stop],
            ["Target", card.plan.target],
          ].map(([label, value]) => (
            <div key={label as string} className="rounded-md bg-muted/60 px-2 py-1.5">
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="font-medium">{rupee(value as number)}</dd>
            </div>
          ))}
        </dl>
      )}
      {card.plan_refused && <p className="text-sm text-warning">Plan refused: {card.plan_refused}</p>}
      {card.odds ? <Odds card={card} /> : card.odds_unavailable && <p className="text-xs text-muted-foreground">Time machine: {card.odds_unavailable}</p>}
      {card.check ? (
        <p className={cn("flex items-start gap-2 text-sm", card.check.verdict === "PASS" ? "text-success" : "text-destructive")}>
          {card.check.verdict === "PASS" ? <ShieldCheck className="mt-0.5 size-4 shrink-0" /> : <ShieldX className="mt-0.5 size-4 shrink-0" />}
          <span>
            {card.check.verdict === "PASS"
              ? `PASS: ${card.check.qty} shares, ${rupee(card.check.cost_inr)}, ${rupee(card.check.planned_loss_inr)} at the stop (${card.check.decided_by} limit)`
              : `BLOCK: ${card.check.blocks.join("; ")}`}
          </span>
        </p>
      ) : (
        card.check_unavailable && <p className="text-xs text-muted-foreground">Trade check: {card.check_unavailable}</p>
      )}
    </article>
  );
}

/** What the desk agent did on its own this session, for each of today's picks. */
export function TradeDeskCard({ desk }: { desk: TradeDesk | null | undefined }) {
  return (
    <Card>
      <CardHeader className="flex-row items-start gap-4 space-y-0">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <Crosshair className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <CardTitle>Trade desk, on its own</CardTitle>
          <CardDescription className="mt-1">
            Every few minutes during the session the desk agent watches each pick for a close above its opening range, sets the stop and target,
            replays the rest of the day thousands of times from the stock's own history, checks the size and limits against your paper book, and
            rings alerts. The paper autopilot records entries; the time machine can veto one. Nothing here touches real money.
          </CardDescription>
          {desk && <p className="mt-2 text-xs text-muted-foreground">Last pass {dateTime(desk.checked_at)}</p>}
        </div>
      </CardHeader>
      <CardContent className="grid gap-5">
        {desk && desk.cards.length > 0 ? (
          <div className="grid gap-4 lg:grid-cols-2">
            {desk.cards.map((card) => (
              <PickCard key={card.symbol} card={card} />
            ))}
          </div>
        ) : (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <Timer className="size-4" /> No pass yet today. It starts with the session worker once the judge has picked.
          </p>
        )}
        <section className="grid gap-2" aria-labelledby="alerts-title">
          <h3 id="alerts-title" className="flex items-center gap-2 text-sm font-medium">
            <BellRing className="size-4" /> Recent alerts
          </h3>
          {desk?.alerts.length ? (
            <ul className="grid gap-1.5 text-sm">
              {desk.alerts.map((alert) => (
                <li key={`${alert.at}-${alert.message}`} className="flex min-w-0 gap-2">
                  <span className="num shrink-0 text-muted-foreground">
                    <Clock3 className="mr-1 inline size-3.5" />
                    {alert.at.slice(11, 16)}
                  </span>
                  <span className="min-w-0 break-words">{alert.message}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">None yet. Every paper entry gets a stop, target and square-off alert.</p>
          )}
        </section>
        <div className="grid gap-3">
          <JobRunner kind="desk_tick" label="Run the trade desk now" description="One pass: entry check, plan, time machine, trade check and alerts for today's picks." />
          <JobRunner kind="insiders" label="Insider-trading filings, last 7 days" description="SEBI disclosures by promoters, directors and key managers, from NSE." />
          <JobRunner kind="alerts_check" label="Check price alerts" />
        </div>
      </CardContent>
    </Card>
  );
}
