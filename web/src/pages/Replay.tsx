import { useEffect, useMemo, useRef, useState } from "react";
import gsap from "gsap";
import { Loader2, OctagonX, Pause, Play } from "lucide-react";
import { post } from "@/lib/api";
import { useData } from "@/lib/context";
import { toast } from "@/lib/toast";
import type { Call, DashboardState } from "@/lib/types";
import { cn, readable, rupees, time } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Mascot, type Mood } from "@/mascots/Mascot";
import type { MascotKey } from "@/mascots/data";
import { Confetti } from "@/mascots/Confetti";

const SCENARIOS = [
  { id: "baseline", label: "Complete data, normal risk checks" },
  { id: "data-gap", label: "Missing opening bars (no entry expected)" },
  { id: "risk-block", label: "Oversized proposal (rejection expected)" },
];

const STAGES: { id: string; mascot: MascotKey; caption: string }[] = [
  { id: "data", mascot: "tide", caption: "Validated candles" },
  { id: "strategy", mascot: "blueprint", caption: "Entry proposals" },
  { id: "risk", mascot: "shield", caption: "Gate passes" },
  { id: "execution", mascot: "pilot", caption: "Virtual fills" },
  { id: "journal", mascot: "echo", caption: "Journal entries" },
];

function counts(state: DashboardState | null): Record<string, number> {
  return {
    data: state?.metrics?.quotes ?? 0,
    strategy: state?.metrics?.proposals ?? 0,
    risk: (state?.events ?? []).filter((event) => event.kind === "risk_passed").length,
    execution: (state?.calls ?? []).filter((call) => call.status === "filled").length,
    journal: state?.metrics?.fills ?? 0,
  };
}

/** The five-stage funnel. When a stage's count rises, an orb hops from the stage before it. */
function Pipeline({ state }: { state: DashboardState | null }) {
  const now = counts(state);
  const previous = useRef(now);
  const row = useRef<HTMLDivElement>(null);
  const orb = useRef<HTMLSpanElement>(null);
  const [pulse, setPulse] = useState<Record<string, number>>({});
  const live = state?.status === "running";

  useEffect(() => {
    const rose = STAGES.findIndex((stage) => now[stage.id] > (previous.current[stage.id] ?? 0));
    previous.current = now;
    if (rose < 0) return;
    const target = STAGES[rose].id;
    setPulse((value) => ({ ...value, [target]: (value[target] ?? 0) + 1 }));
    if (rose === 0 || !row.current || !orb.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const from = row.current.querySelector<HTMLElement>(`[data-stage="${STAGES[rose - 1].id}"]`);
    const to = row.current.querySelector<HTMLElement>(`[data-stage="${target}"]`);
    if (!from || !to) return;
    const box = row.current.getBoundingClientRect();
    const a = from.getBoundingClientRect();
    const b = to.getBoundingClientRect();
    const start = { x: a.left - box.left + a.width / 2, y: a.top - box.top + 34 };
    const end = { x: b.left - box.left + b.width / 2, y: b.top - box.top + 34 };
    gsap
      .timeline()
      .set(orb.current, { x: start.x, y: start.y, autoAlpha: 1, scale: 0.6 })
      .to(orb.current, { x: (start.x + end.x) / 2, y: Math.min(start.y, end.y) - 30, scale: 1, duration: 0.35, ease: "power1.out" })
      .to(orb.current, { x: end.x, y: end.y, scale: 0.5, duration: 0.35, ease: "power1.in" })
      .to(orb.current, { autoAlpha: 0, duration: 0.15 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [now.data, now.strategy, now.risk, now.execution, now.journal]);

  const agents = state?.agents ?? [];
  return (
    <div ref={row} className="relative grid grid-cols-2 gap-3 sm:grid-cols-5">
      <span ref={orb} aria-hidden className="pointer-events-none invisible absolute left-0 top-0 z-10 -ml-2 -mt-2 size-4 rounded-full bg-primary shadow-[0_0_16px_hsl(var(--primary))]" />
      {STAGES.map((stage, index) => {
        const agent = agents.find((item) => item.id === stage.id);
        const blocked = agent?.status === "blocked";
        const mood: Mood = blocked ? "alert" : live && now[stage.id] === 0 && index > 0 ? "thinking" : now[stage.id] ? "happy" : live ? "thinking" : "idle";
        return (
          <div key={stage.id} data-stage={stage.id} className={cn("flex flex-col items-center rounded-lg border p-3 text-center", blocked && "border-destructive/50 bg-destructive/5")}>
            <Mascot kind={stage.mascot} size={68} mood={mood} react={pulse[stage.id] ?? 0} />
            <p className="mt-1 text-sm font-medium">{agent?.name ?? readable(stage.id)}</p>
            <p className="text-xs text-muted-foreground">{stage.caption}</p>
            <p className="num mt-1 text-xl font-semibold">{now[stage.id]}</p>
            {blocked && <Badge variant="destructive" className="mt-1">Blocked</Badge>}
          </div>
        );
      })}
    </div>
  );
}

function PriceChart({ state }: { state: DashboardState | null }) {
  const prices = (state?.prices ?? []).map((item) => ({ at: item.at, price: Number(item.price) })).filter((item) => Number.isFinite(item.price));
  const fills = (state?.calls ?? []).filter((call) => call.status === "filled" && call.fill_inr);
  const position = Object.values(state?.positions ?? {})[0];
  const width = 720;
  const height = 240;
  const pad = { l: 56, r: 16, t: 16, b: 28 };
  const levels = [position?.stop_inr, position?.target_inr, ...fills.map((fill) => fill.fill_inr)].map(Number).filter(Number.isFinite);
  const values = [...prices.map((item) => item.price), ...levels];
  if (prices.length < 2) {
    return (
      <div className="grid h-60 place-items-center rounded-lg border border-dashed text-sm text-muted-foreground">
        Start a replay to draw the session here.
      </div>
    );
  }
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = high - low || 1;
  const x = (index: number) => pad.l + (index / (prices.length - 1)) * (width - pad.l - pad.r);
  const y = (value: number) => pad.t + (1 - (value - low) / span) * (height - pad.t - pad.b);
  const indexOf = (at?: string) => {
    if (!at) return prices.length - 1;
    const found = prices.findIndex((item) => item.at >= at);
    return found < 0 ? prices.length - 1 : found;
  };
  const line = prices.map((item, index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(item.price).toFixed(1)}`).join(" ");
  const area = `${line} L${x(prices.length - 1)},${height - pad.b} L${x(0)},${height - pad.b} Z`;
  const ticks = [low, low + span / 2, high];
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-auto w-full" role="img" aria-label={`Bid price over the replayed session, from ${rupees(prices[0].price, true)} to ${rupees(prices.at(-1)!.price, true)}`}>
      <defs>
        <linearGradient id="replay-area" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="hsl(var(--primary))" stopOpacity="0.22" />
          <stop offset="1" stopColor="hsl(var(--primary))" stopOpacity="0" />
        </linearGradient>
      </defs>
      {ticks.map((tick) => (
        <g key={tick}>
          <line x1={pad.l} x2={width - pad.r} y1={y(tick)} y2={y(tick)} className="stroke-border" strokeDasharray="3 4" />
          <text x={pad.l - 8} y={y(tick) + 4} textAnchor="end" className="fill-muted-foreground text-[11px] tabular-nums">
            {tick.toFixed(2)}
          </text>
        </g>
      ))}
      {[0, Math.floor(prices.length / 2), prices.length - 1].map((index) => (
        <text key={index} x={x(index)} y={height - 8} textAnchor={index === 0 ? "start" : index === prices.length - 1 ? "end" : "middle"} className="fill-muted-foreground text-[11px]">
          {time(prices[index].at)}
        </text>
      ))}
      <path d={area} fill="url(#replay-area)" />
      <path d={line} fill="none" stroke="hsl(var(--primary))" strokeWidth="2" strokeLinejoin="round" />
      {position?.stop_inr && (
        <g>
          <line x1={pad.l} x2={width - pad.r} y1={y(Number(position.stop_inr))} y2={y(Number(position.stop_inr))} stroke="hsl(var(--destructive))" strokeDasharray="6 4" />
          <text x={width - pad.r} y={y(Number(position.stop_inr)) - 5} textAnchor="end" className="fill-destructive text-[11px] font-medium">
            Stop {Number(position.stop_inr).toFixed(2)}
          </text>
        </g>
      )}
      {position?.target_inr && (
        <g>
          <line x1={pad.l} x2={width - pad.r} y1={y(Number(position.target_inr))} y2={y(Number(position.target_inr))} stroke="hsl(var(--success))" strokeDasharray="6 4" />
          <text x={width - pad.r} y={y(Number(position.target_inr)) - 5} textAnchor="end" className="fill-success text-[11px] font-medium">
            Target {Number(position.target_inr).toFixed(2)}
          </text>
        </g>
      )}
      {fills.map((fill, index) => {
        const cx = x(indexOf(fill.at));
        const cy = y(Number(fill.fill_inr));
        const buy = fill.side === "buy";
        return (
          <g key={index}>
            <circle cx={cx} cy={cy} r="6" fill={buy ? "hsl(var(--success))" : "hsl(var(--destructive))"} stroke="hsl(var(--card))" strokeWidth="2" />
            <text x={cx} y={buy ? cy + 20 : cy - 12} textAnchor="middle" className="fill-foreground text-[11px] font-semibold">
              {buy ? "Buy" : "Sell"}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

const BLOCKS = ["entry_blocked", "quote_rejected", "strategy_blocked", "halt", "reconcile_mismatch", "manual_attention"];

export function ReplayPage() {
  const { state, refreshState } = useData();
  const [scenario, setScenario] = useState("baseline");
  const [busy, setBusy] = useState<string | null>(null);
  const [filter, setFilter] = useState<"all" | "blocks">("all");
  const [burst, setBurst] = useState(0);
  const status = state?.status ?? "idle";
  const active = ["running", "paused", "halting"].includes(status);
  const calls: Call[] = state?.calls ?? [];
  const targetExits = calls.filter((call) => call.side === "sell" && call.status === "filled" && /target/i.test(call.reason ?? "")).length;
  const seenExits = useRef(targetExits);
  useEffect(() => {
    if (targetExits > seenExits.current) setBurst((value) => value + 1);
    seenExits.current = targetExits;
  }, [targetExits]);

  const events = useMemo(() => {
    const list = (state?.events ?? []) as (Record<string, string | number | undefined> & { kind?: string })[];
    return list
      .filter((event) => filter === "all" || BLOCKS.includes(String(event.kind)) || event.status === "rejected")
      .slice(-40)
      .reverse();
  }, [state?.events, filter]);

  async function act(name: string, path: string, payload: object, success: string) {
    setBusy(name);
    try {
      await post(path, payload);
      await refreshState();
      toast.success(success);
    } catch (error) {
      toast.error("That didn't work", (error as Error).message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader className="flex-row flex-wrap items-start justify-between gap-4 space-y-0">
          <div>
            <CardTitle>Paper replay</CardTitle>
            <CardDescription className="mt-1 max-w-2xl">
              Replays the bundled NSE:DEMO session through the same pipeline the desk uses. Every price and fill here is synthetic, so you can see
              how a decision travels without waiting for the market.
            </CardDescription>
          </div>
          <Badge variant={status === "running" ? "success" : status === "error" ? "destructive" : "outline"} >
            {status === "running" && <span className="size-1.5 animate-pulse-dot rounded-full bg-current" />}
            {readable(status).replace(/^./, (c) => c.toUpperCase())}
            {state?.clock ? ` · ${time(state.clock)}` : ""}
          </Badge>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <div className="grid w-full gap-1.5 sm:w-72">
            <span className="text-sm font-medium">Scenario</span>
            <Select value={scenario} onValueChange={setScenario} disabled={active}>
              <SelectTrigger aria-label="Scenario">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SCENARIOS.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button disabled={active || busy !== null} onClick={() => act("start", "/api/replay", { scenario }, "Replay started")}>
            {busy === "start" ? <Loader2 className="animate-spin" /> : <Play />} Start replay
          </Button>
          {active && (
            <>
              <Button variant="outline" disabled={busy !== null || status === "halting"} onClick={() => act("pause", "/api/control", { action: status === "paused" ? "resume" : "pause" }, status === "paused" ? "Resumed" : "Paused")}>
                {status === "paused" ? <Play /> : <Pause />} {status === "paused" ? "Resume" : "Pause"}
              </Button>
              <Button variant="destructive" disabled={busy !== null || status === "halting"} onClick={() => act("halt", "/api/control", { action: "halt" }, "New entries halted")}>
                <OctagonX /> Halt entries
              </Button>
            </>
          )}
          {state?.halt_reason && <p className="basis-full text-sm text-destructive">Halted: {state.halt_reason}</p>}
          {state?.error && <p className="basis-full text-sm text-destructive">{state.error}</p>}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>How a decision travels</CardTitle>
          <CardDescription>Data, then a strategy proposal, then the risk gate, then a virtual fill, then the sealed journal.</CardDescription>
        </CardHeader>
        <CardContent>
          <Pipeline state={state} />
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[1.6fr_1fr]">
        <Card className="relative">
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle>Session price</CardTitle>
              <CardDescription>Recorded bids, with paper fills, stop and target.</CardDescription>
            </div>
            <div className="relative">
              <Confetti fire={burst} />
            </div>
          </CardHeader>
          <CardContent>
            <PriceChart state={state} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Risk limits</CardTitle>
            <CardDescription>Fixed by code, not by any agent.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            {[
              ["Risk per trade", rupees(state?.limits?.risk)],
              ["Daily loss limit", rupees(state?.limits?.daily_loss)],
              ["Largest position", rupees(state?.limits?.position_limit)],
              ["Entry halt", state?.halt_reason ? "Active" : "Not active"],
              ["Real orders", "Not possible (no order code)"],
            ].map(([label, value]) => (
              <div key={label} className="flex justify-between gap-3 border-b pb-2 last:border-0">
                <span className="text-muted-foreground">{label}</span>
                <span className="num font-medium">{value}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Paper calls</CardTitle>
            <CardDescription>{calls.length ? `${calls.length} recorded` : "Waiting is a valid decision."}</CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <thead>
                <tr>
                  <Th>Time</Th>
                  <Th>Side</Th>
                  <Th>Qty</Th>
                  <Th>Fill</Th>
                  <Th>Why</Th>
                  <Th>Result</Th>
                </tr>
              </thead>
              <tbody>
                {calls.length ? (
                  [...calls].reverse().map((call, index) => (
                    <tr key={index}>
                      <Td className="num">{time(call.at)}</Td>
                      <Td>
                        <Badge variant={call.side === "buy" ? "success" : "outline"} className="uppercase">
                          {call.side}
                        </Badge>
                      </Td>
                      <Td className="num">{call.qty}</Td>
                      <Td className="num">{rupees(call.fill_inr, true)}</Td>
                      <Td className="text-muted-foreground">{readable(call.reason)}</Td>
                      <Td>
                        <Badge variant={call.status === "filled" ? "default" : "destructive"}>{call.status === "filled" ? "Paper fill" : call.status}</Badge>
                      </Td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <Td colSpan={6} className="py-8 text-center text-muted-foreground">
                      No calls yet.
                    </Td>
                  </tr>
                )}
              </tbody>
            </Table>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle>Engine events</CardTitle>
              <CardDescription>The last 40, newest first.</CardDescription>
            </div>
            <div className="flex gap-1 rounded-md bg-muted p-1 text-sm" role="group" aria-label="Filter events">
              {(["all", "blocks"] as const).map((value) => (
                <button key={value} onClick={() => setFilter(value)} aria-pressed={filter === value} className={cn("rounded px-2.5 py-1", filter === value ? "bg-card shadow-sm" : "text-muted-foreground")}>
                  {value === "all" ? "All" : "Blocks"}
                </button>
              ))}
            </div>
          </CardHeader>
          <CardContent>
            <ol className="grid max-h-96 gap-2 overflow-auto pr-1">
              {events.length ? (
                events.map((event, index) => (
                  <li key={index} className="flex gap-3 text-sm">
                    <span className="num w-16 shrink-0 whitespace-nowrap text-muted-foreground">{time(String(event.at ?? ""))}</span>
                    <div className="min-w-0">
                      <p className={cn("font-medium capitalize", BLOCKS.includes(String(event.kind)) && "text-destructive")}>
                        {readable(String(event.kind))}
                        {event.symbol ? ` · ${event.symbol}` : ""}
                      </p>
                      <p className="truncate text-muted-foreground">{String(event.detail ?? event.reason ?? event.phase ?? "")}</p>
                    </div>
                  </li>
                ))
              ) : (
                <li className="text-sm text-muted-foreground">No matching events.</li>
              )}
            </ol>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
