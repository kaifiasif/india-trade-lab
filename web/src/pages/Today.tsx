import { useEffect, useRef, useState } from "react";
import gsap from "gsap";
import { ArrowRight, CircleCheck, CircleDashed, ShieldCheck, TrendingDown, TrendingUp, Wallet } from "lucide-react";
import { useData } from "@/lib/context";
import { useNow } from "@/lib/hooks";
import { cn, rupees, signed } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress, Skeleton } from "@/components/ui/misc";
import { Mascot, type Mood } from "@/mascots/Mascot";
import { Confetti } from "@/mascots/Confetti";

function greeting(now: Date) {
  const hour = Number(now.toLocaleString("en-US", { hour: "numeric", hour12: false, timeZone: "Asia/Kolkata" }));
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

function CountUp({ value, format }: { value: number | null; format: (value: number) => string }) {
  const ref = useRef<HTMLSpanElement>(null);
  const last = useRef(0);
  useEffect(() => {
    if (value === null || !ref.current) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      ref.current.textContent = format(value);
      last.current = value;
      return;
    }
    const box = { v: last.current };
    const tween = gsap.to(box, {
      v: value,
      duration: 0.9,
      ease: "power2.out",
      onUpdate: () => {
        if (ref.current) ref.current.textContent = format(box.v);
      },
    });
    last.current = value;
    return () => {
      tween.kill();
    };
  }, [value, format]);
  return <span ref={ref} className="num">{value === null ? "—" : format(value)}</span>;
}

const TIMELINE = [
  { at: "08:30", minutes: 510, title: "Kite login", who: "You" },
  { at: "08:40", minutes: 520, title: "Overnight scan of all F&O stocks", who: "Code: positioning, events, news" },
  { at: "09:09", minutes: 549, title: "Open scan, agents and judge", who: "Picks emailed; you confirm the two checks" },
  { at: "09:15", minutes: 555, title: "Market opens", who: "Desk watches picks" },
  { at: "09:31", minutes: 571, title: "Volume and VWAP check", who: "Code: unconfirmed picks are not entered" },
  { at: "14:30", minutes: 870, title: "Last new entry", who: "Code" },
  { at: "15:15", minutes: 915, title: "Square-off", who: "Code" },
  { at: "16:10", minutes: 970, title: "History and tournament", who: "Code" },
];

function DayTimeline() {
  const now = useNow(60_000);
  const ist = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const minutes = ist.getHours() * 60 + ist.getMinutes();
  const nextIndex = TIMELINE.findIndex((step) => step.minutes > minutes);
  return (
    <ol className="relative grid gap-4 pl-6 before:absolute before:left-[7px] before:top-1 before:h-[calc(100%-0.5rem)] before:w-px before:bg-border">
      {TIMELINE.map((step, index) => {
        const done = nextIndex === -1 || index < nextIndex;
        const current = index === nextIndex;
        return (
          <li key={step.at} className="relative">
            <span
              className={cn(
                "absolute -left-6 top-1 grid size-[15px] place-items-center rounded-full border-2 bg-card",
                done ? "border-primary bg-primary" : current ? "border-primary" : "border-border",
              )}
              aria-hidden
            >
              {current && <span className="size-1.5 animate-pulse-dot rounded-full bg-primary" />}
            </span>
            <div className="flex items-baseline gap-3">
              <span className={cn("num w-12 shrink-0 text-sm font-semibold", current ? "text-primary" : "text-muted-foreground")}>{step.at}</span>
              <div>
                <p className={cn("text-sm font-medium", done && "text-muted-foreground")}>{step.title}</p>
                <p className="text-xs text-muted-foreground">{step.who}</p>
              </div>
              {current && <Badge className="ml-auto">Next</Badge>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function TodayPage() {
  const { state, setup } = useData();
  const now = useNow();
  const desk = state?.desk?.report ?? null;
  const card = state?.desk?.scorecard ?? null;
  const [burst, setBurst] = useState(0);
  const picksKey = desk ? `${desk.session_date}:${desk.watching.join(",")}` : null;
  const seen = useRef<string | null>(null);
  useEffect(() => {
    if (picksKey && seen.current && seen.current !== picksKey && desk?.picks.length) setBurst((value) => value + 1);
    seen.current = picksKey;
  }, [picksKey, desk?.picks.length]);

  const mood: Mood = !desk ? "idle" : desk.mode === "sit_out" ? "sleep" : desk.picks.length ? "happy" : "idle";
  const name = setup?.profile?.name?.split(" ")[0];
  const steps = setup?.steps ?? [];
  const done = steps.filter((step) => step.done).length;
  const nextStep = steps.find((step) => !step.done);
  const metrics = state?.metrics ?? {};
  const realized = metrics.realized_inr === undefined ? null : Number(metrics.realized_inr);
  const proven = card ? Object.entries(card.strategies).filter(([, item]) => item.eligible).map(([key]) => key) : [];

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-5 rounded-xl border bg-card p-5 sm:flex-row sm:items-center sm:p-6">
        <div className="relative shrink-0 self-center">
          <Mascot kind="judge" size={112} mood={mood} entrance="pop" react={picksKey} title="Justice, the selection judge" />
          <Confetti fire={burst} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-sm text-muted-foreground">
            {now.toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata" })}
          </p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight sm:text-3xl">
            {greeting(now)}
            {name ? `, ${name}` : ""}.
          </h2>
          <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-muted-foreground">
            {!desk
              ? "No picks yet today. The desk scans at 08:40 and picks at 09:09 on the server, or run it from the desk page."
              : desk.mode === "sit_out"
                ? `The desk is sitting out today: ${desk.reason}.`
                : desk.picks.length
                  ? `The judge picked ${desk.picks.map((pick) => pick.symbol.replace("NSE:", "")).join(", ")} to watch at the open.`
                  : `No picks today. ${desk.reason}.`}
          </p>
        </div>
        <div className="flex gap-2 sm:flex-col">
          <Button asChild>
            <a href="#/desk">
              Open the desk <ArrowRight />
            </a>
          </Button>
        </div>
      </section>

      {setup && done < steps.length && (
        <Card>
          <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center">
            <Mascot kind="blueprint" size={64} mood="thinking" />
            <div className="min-w-0 flex-1">
              <p className="font-medium">
                Setup: {done} of {steps.length} done
              </p>
              <p className="text-sm text-muted-foreground">
                Next: <span className="text-foreground">{nextStep?.label}</span> · {nextStep?.detail}
              </p>
              <Progress value={(done / steps.length) * 100} className="mt-3 max-w-md" />
            </div>
            <Button variant="outline" asChild>
              <a href={`#/setup?step=${nextStep?.id ?? ""}`}>Continue setup</a>
            </Button>
          </CardContent>
        </Card>
      )}

      <section aria-label="Paper book" className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        {[
          { label: "Virtual equity", icon: Wallet, value: metrics.equity_inr === undefined ? null : Number(metrics.equity_inr), format: (v: number) => rupees(v) },
          { label: "Realised P&L", icon: realized !== null && realized < 0 ? TrendingDown : TrendingUp, value: realized, format: (v: number) => signed(v), tone: realized === null ? "" : realized > 0 ? "text-success" : realized < 0 ? "text-destructive" : "" },
          { label: "Open positions", icon: ShieldCheck, value: metrics.open_positions ?? null, format: (v: number) => String(Math.round(v)) },
          { label: "Picks today", icon: CircleCheck, value: desk ? desk.picks.length : null, format: (v: number) => String(Math.round(v)) },
        ].map((item) =>
          state ? (
            <Card key={item.label}>
              <CardContent className="p-5">
                <div className="flex items-center justify-between text-sm text-muted-foreground">
                  {item.label}
                  <item.icon className="size-4" aria-hidden />
                </div>
                <p className={cn("mt-2 text-2xl font-semibold tracking-tight", item.tone)}>
                  <CountUp value={item.value} format={item.format} />
                </p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {item.label === "Picks today" ? (desk ? `From ${desk.assessed} stocks assessed` : "No report yet") : state.mode === "synthetic_replay" ? "Latest paper replay" : "Paper book"}
                </p>
              </CardContent>
            </Card>
          ) : (
            <Skeleton key={item.label} className="h-[118px]" />
          ),
        )}
      </section>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Today's picks</CardTitle>
            <CardDescription>Chosen by the judge before the open. A pick is a stock to watch, not an order.</CardDescription>
          </CardHeader>
          <CardContent>
            {desk?.picks.length ? (
              <ul className="divide-y">
                {desk.picks.map((pick) => (
                  <li key={pick.symbol} className="flex flex-wrap items-center gap-x-4 gap-y-1 py-3">
                    <span className="w-28 font-semibold">{pick.symbol.replace("NSE:", "")}</span>
                    <Badge variant={pick.rating === "Buy" ? "success" : "default"}>{pick.rating}</Badge>
                    <span className="text-sm text-muted-foreground">{pick.conviction} conviction</span>
                    <span className="text-sm text-muted-foreground">· {pick.strategy ?? "any proven strategy"}</span>
                    {pick.risk && (
                      <Badge variant={pick.risk === "low" ? "outline" : "warning"} className="ml-auto">
                        Risk {pick.risk}
                      </Badge>
                    )}
                    <p className="basis-full text-sm text-muted-foreground">{pick.reason}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="flex items-center gap-4 rounded-lg border border-dashed p-5">
                <Mascot kind={desk?.mode === "sit_out" ? "ref" : "scout"} size={60} mood={desk?.mode === "sit_out" ? "sleep" : "idle"} />
                <div className="text-sm">
                  <p className="font-medium">{desk ? "Nothing to watch today" : "Waiting for the morning report"}</p>
                  <p className="text-muted-foreground">
                    {desk ? desk.reason : "Picks appear here after the 08:40 report. Nothing is invented in the meantime."}
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Today, step by step</CardTitle>
            <CardDescription>India Standard Time, NSE trading days.</CardDescription>
          </CardHeader>
          <CardContent>
            <DayTimeline />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-4">
          <div>
            <CardTitle>Strategy tournament</CardTitle>
            <CardDescription>A strategy may trade only if it made money at double costs on your own history.</CardDescription>
          </div>
          {card && <Badge variant={proven.length ? "success" : "warning"}>{proven.length ? `${proven.length} proven` : "Sitting out"}</Badge>}
        </CardHeader>
        <CardContent>
          {card ? (
            <div className="grid gap-3 sm:grid-cols-2">
              {Object.entries(card.strategies).map(([name, item]) => (
                <div key={name} className="flex items-start gap-3 rounded-lg border p-4">
                  {item.eligible ? <CircleCheck className="mt-0.5 size-5 text-success" /> : <CircleDashed className="mt-0.5 size-5 text-muted-foreground" />}
                  <div className="min-w-0 text-sm">
                    <p className="font-medium">{name}</p>
                    <p className="text-muted-foreground">
                      {item.eligible ? "Proven at double costs" : item.reason}
                      {item.doubled_costs?.trades !== undefined && ` · ${item.doubled_costs.trades} trades`}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">No tournament yet. It runs each evening after the history sync, or from Setup.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
