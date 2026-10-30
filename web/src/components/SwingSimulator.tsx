import { useEffect, useState } from "react";
import { Dices, Loader2 } from "lucide-react";
import { setup } from "@/lib/api";
import type { SwingCandidate, SwingOdds } from "@/lib/types";
import { cn } from "@/lib/utils";
import { toast } from "@/lib/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/misc";
import { explain } from "@/components/setup-kit";

export const inr = (value: number) => `${value >= 0 ? "+" : "−"}₹${Math.abs(Math.round(value)).toLocaleString("en-IN")}`;

export function isOdds(value: unknown): value is SwingOdds {
  return Boolean(value && typeof value === "object" && "expected_pnl_inr" in value);
}

/** How many replays ended in each rupee band: losses red, gains green. */
function Histogram({ odds }: { odds: SwingOdds }) {
  const { counts, from_inr, width_inr } = odds.histogram;
  const peak = Math.max(...counts, 1);
  const width = 320;
  const height = 110;
  const bar = width / counts.length;
  const zero = Math.min(width, Math.max(0, ((0 - from_inr) / (width_inr * counts.length)) * width));
  return (
    <figure className="grid gap-1">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-28 w-full" role="img" aria-label="Distribution of profit and loss after costs across the replays">
        {counts.map((count, index) => {
          const middle = from_inr + (index + 0.5) * width_inr;
          const h = (count / peak) * (height - 4);
          return <rect key={index} x={index * bar + 1} width={Math.max(1, bar - 2)} y={height - h} height={h} className={middle < 0 ? "fill-destructive/70" : "fill-success/70"} />;
        })}
        <line x1={zero} x2={zero} y1={0} y2={height} className="stroke-foreground/50" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="num flex justify-between text-xs text-muted-foreground">
        <span>{inr(from_inr)}</span>
        <span>₹0</span>
        <span>{inr(from_inr + width_inr * counts.length)}</span>
      </figcaption>
    </figure>
  );
}

/** Chance of having hit the target, or been stopped, by the end of each session. */
function ByDay({ odds }: { odds: SwingOdds }) {
  const width = 320;
  const height = 110;
  const days = odds.by_day;
  const x = (index: number) => (days.length === 1 ? width / 2 : (index / (days.length - 1)) * (width - 20) + 10);
  const y = (pct: number) => height - 8 - (pct / 100) * (height - 16);
  const line = (key: "target_pct" | "stopped_pct") => days.map((day, index) => `${x(index)},${y(day[key])}`).join(" ");
  return (
    <figure className="grid gap-1">
      <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" className="h-28 w-full" role="img" aria-label="Cumulative chance of target and of stop by session">
        <polyline points={line("target_pct")} className="fill-none stroke-success" strokeWidth={2} vectorEffect="non-scaling-stroke" />
        <polyline points={line("stopped_pct")} className="fill-none stroke-destructive" strokeWidth={2} vectorEffect="non-scaling-stroke" />
      </svg>
      <figcaption className="num flex justify-between text-xs text-muted-foreground">
        {days.map((day) => (
          <span key={day.day}>
            D{day.day}: <span className="text-success">{day.target_pct}%</span> / <span className="text-destructive">{day.stopped_pct}%</span>
          </span>
        ))}
      </figcaption>
    </figure>
  );
}

export function OddsView({ odds }: { odds: SwingOdds }) {
  const tiles = [
    { label: "Expected after costs", value: inr(odds.expected_pnl_inr), tone: odds.expected_pnl_inr >= 0 ? "text-success" : "text-destructive" },
    { label: "Chance of profit", value: `${odds.profit_pct}%` },
    { label: "Target first", value: `${odds.target_pct}%`, tone: "text-success" },
    { label: "Stopped (incl. gaps)", value: `${odds.stopped_pct}%`, tone: "text-destructive" },
    { label: "Median", value: inr(odds.median_pnl_inr) },
    { label: "1 in 20 worse than", value: inr(odds.p5_pnl_inr) },
  ];
  return (
    <div className="grid gap-4">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {tiles.map((tile) => (
          <div key={tile.label} className="rounded-lg bg-muted/60 p-3">
            <p className="text-xs text-muted-foreground">{tile.label}</p>
            <p className={cn("num mt-1 text-lg font-semibold", tile.tone)}>{tile.value}</p>
          </div>
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid gap-1">
          <p className="text-sm font-medium">Profit and loss after costs</p>
          <Histogram odds={odds} />
        </div>
        <div className="grid gap-1">
          <p className="text-sm font-medium">
            By session: <span className="text-success">target</span> vs <span className="text-destructive">stopped</span>
          </p>
          <ByDay odds={odds} />
        </div>
      </div>
      <p className="text-sm">{odds.summary}</p>
      <p className="num text-xs text-muted-foreground">
        {odds.qty} shares · planned loss at the stop {inr(-odds.planned_loss_inr)} · average of the worst 5% {inr(odds.worst_5pct_avg_inr)} · worst {inr(odds.worst_inr)} ·
        middle half {inr(odds.p25_pnl_inr)} to {inr(odds.p75_pnl_inr)} · {odds.replays.toLocaleString("en-IN")} replays from {odds.days_in_pool} days, seed {odds.seed}
      </p>
    </div>
  );
}

/** Try a swing plan before the desk would: change the stop, target or holding days and replay. */
export function SwingSimulator({ candidates }: { candidates: SwingCandidate[] }) {
  const first = candidates[0];
  const [plan, setPlan] = useState({
    symbol: first?.symbol.replace("NSE:", "") ?? "",
    entry: first ? String(first.close) : "",
    stop: first ? String(first.stop) : "",
    target: first ? String(first.target) : "",
    hold_days: "5",
  });
  const [odds, setOdds] = useState<SwingOdds | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (first && !plan.symbol) setPlan({ symbol: first.symbol.replace("NSE:", ""), entry: String(first.close), stop: String(first.stop), target: String(first.target), hold_days: "5" });
  }, [first, plan.symbol]);
  const pick = (symbol: string) => {
    const row = candidates.find((item) => item.symbol === symbol);
    if (row) setPlan({ symbol: row.symbol.replace("NSE:", ""), entry: String(row.close), stop: String(row.stop), target: String(row.target), hold_days: plan.hold_days });
  };
  const numeric = (value: string) => value.replace(/[^0-9.]/g, "");
  async function run() {
    setBusy(true);
    try {
      setOdds(await setup<SwingOdds>("swing_simulate", { ...plan, hold_days: Number(plan.hold_days), replays: 5000 }));
    } catch (error) {
      toast.error("Simulation not run", explain(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="grid gap-4 rounded-lg border p-4" aria-labelledby="sim-title">
      <div className="flex items-center gap-2">
        <Dices className="size-4 text-primary" />
        <h3 id="sim-title" className="font-medium">Scenario simulator</h3>
      </div>
      <p className="-mt-2 text-sm text-muted-foreground">
        Replays the next few sessions 5,000 times from this stock's own daily candles, overnight gaps included, with the desk's exit rules and
        delivery costs. Change the stop, target or holding days and run it again.
      </p>
      {candidates.length > 0 && (
        <div className="flex flex-wrap gap-2" role="group" aria-label="Load a candidate">
          {candidates.map((row) => (
            <Button key={row.symbol} size="sm" variant={plan.symbol === row.symbol.replace("NSE:", "") ? "default" : "outline"} onClick={() => pick(row.symbol)}>
              {row.symbol.replace("NSE:", "")}
            </Button>
          ))}
        </div>
      )}
      <form
        className="grid grid-cols-2 gap-3 sm:grid-cols-5"
        onSubmit={(event) => {
          event.preventDefault();
          run();
        }}
      >
        <Field label="Stock" htmlFor="sim-symbol">
          <Input id="sim-symbol" className="font-mono uppercase" value={plan.symbol} onChange={(event) => setPlan({ ...plan, symbol: event.target.value.toUpperCase().replace(/[^A-Z0-9&-]/g, "") })} />
        </Field>
        {(["entry", "stop", "target"] as const).map((key) => (
          <Field key={key} label={key[0].toUpperCase() + key.slice(1)} htmlFor={`sim-${key}`}>
            <Input id={`sim-${key}`} inputMode="decimal" className="num" value={plan[key]} onChange={(event) => setPlan({ ...plan, [key]: numeric(event.target.value) })} />
          </Field>
        ))}
        <Field label="Hold (sessions)" htmlFor="sim-days">
          <Input id="sim-days" inputMode="numeric" className="num" value={plan.hold_days} onChange={(event) => setPlan({ ...plan, hold_days: event.target.value.replace(/\D/g, "").slice(0, 2) })} />
        </Field>
        <Button type="submit" className="col-span-2 w-fit sm:col-span-5" disabled={busy || !plan.symbol || !plan.entry || !plan.stop || !plan.target}>
          {busy ? <Loader2 className="animate-spin" /> : <Dices />} Simulate
        </Button>
      </form>
      {odds && <OddsView odds={odds} />}
    </section>
  );
}
