import { CircleCheck, CircleSlash, CircleX, Radar, ShieldAlert } from "lucide-react";
import type { DeskState } from "@/lib/types";
import { cn } from "@/lib/utils";
import { useData } from "@/lib/context";
import { dateTime, readable } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/misc";
import { JobRunner } from "@/components/setup-kit";
import { TradeDeskCard } from "@/components/TradeDeskCard";
import { Mascot } from "@/mascots/Mascot";
import type { MascotKey } from "@/mascots/data";

const SPECIALIST: Record<string, { mascot: MascotKey; label: string }> = {
  "news-analyst": { mascot: "scoop", label: "News" },
  "sentiment-analyst": { mascot: "vibe", label: "Sentiment" },
  "technical-analyst": { mascot: "chartly", label: "Technicals" },
  "sector-analyst": { mascot: "atlas", label: "Sector" },
  "liquidity-analyst": { mascot: "tide", label: "Liquidity" },
  "brokerage-analyst": { mascot: "ledger", label: "Brokerage views" },
  "risk-scout": { mascot: "scout", label: "Risk scout" },
  "setup-planner": { mascot: "blueprint", label: "Setup planner" },
};

export function DeskPage() {
  const { state } = useData();
  const desk = state?.desk?.report ?? null;
  const card = state?.desk?.scorecard ?? null;

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader className="flex-row items-start gap-4 space-y-0">
          <Mascot kind="judge" size={72} mood={!desk ? "idle" : desk.mode === "sit_out" ? "sleep" : "happy"} entrance="pop" />
          <div className="min-w-0 flex-1">
            <CardTitle>Pre-market desk</CardTitle>
            <CardDescription className="mt-1">
              {desk ? `Session ${desk.session_date} · prepared ${dateTime(desk.as_of)}` : "No report for today yet."}
            </CardDescription>
            {desk && (
              <p className="mt-3 max-w-3xl text-[15px] leading-relaxed">
                {desk.summary || desk.reason}
              </p>
            )}
          </div>
          {desk && <Badge variant={desk.mode === "sit_out" ? "warning" : "success"}>{desk.mode === "sit_out" ? "Sitting out" : readable(desk.mode)}</Badge>}
        </CardHeader>
        {desk && (
          <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["Stocks in pool", desk.pool],
              ["Assessed", desk.assessed],
              ["Picks", desk.picks.length],
              ["Proven strategies", desk.strategies.length],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg bg-muted/60 p-3">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className="num mt-1 text-xl font-semibold">{value}</p>
              </div>
            ))}
          </CardContent>
        )}
      </Card>

      <div className="grid gap-6 xl:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Picks</CardTitle>
            <CardDescription>The judge may only narrow or veto; code still sizes every trade from your risk limits.</CardDescription>
          </CardHeader>
          <CardContent>
            {desk?.picks.length ? (
              <Table>
                <thead>
                  <tr>
                    <Th>Stock</Th>
                    <Th>Rating</Th>
                    <Th>Conviction</Th>
                    <Th>Strategy</Th>
                    <Th>Risk</Th>
                  </tr>
                </thead>
                <tbody>
                  {desk.picks.map((pick) => (
                    <tr key={pick.symbol} className="align-top">
                      <Td className="font-medium">
                        {pick.symbol.replace("NSE:", "")}
                        <p className="mt-1 max-w-sm text-xs font-normal text-muted-foreground">{pick.reason}</p>
                      </Td>
                      <Td>
                        <Badge variant={pick.rating === "Buy" ? "success" : "default"}>{pick.rating}</Badge>
                      </Td>
                      <Td className="capitalize">{pick.conviction}</Td>
                      <Td className="font-mono text-xs">{pick.strategy ?? "any proven"}</Td>
                      <Td>{pick.risk ? <Badge variant={pick.risk === "low" ? "outline" : "warning"}>{pick.risk}</Badge> : "—"}</Td>
                    </tr>
                  ))}
                </tbody>
              </Table>
            ) : (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <CircleSlash className="size-4" /> {desk ? desk.reason : "Picks appear here after the morning report."}
              </p>
            )}
            {desk && desk.dropped.length > 0 && (
              <div className="mt-6">
                <p className="mb-2 flex items-center gap-2 text-sm font-medium">
                  <ShieldAlert className="size-4 text-warning" /> Dropped before the open
                </p>
                <ul className="grid gap-1.5 text-sm">
                  {desk.dropped.map((item) => (
                    <li key={item.symbol} className="flex gap-3">
                      <span className="w-24 shrink-0 font-medium">{item.symbol.replace("NSE:", "")}</span>
                      <span className="text-muted-foreground">{item.why}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Specialists</CardTitle>
            <CardDescription>Each agent's one-line view. They advise; they cannot place anything.</CardDescription>
          </CardHeader>
          <CardContent>
            {desk && Object.keys(desk.specialists).length ? (
              <ul className="grid gap-3">
                {Object.entries(desk.specialists).map(([key, note]) => {
                  const who = SPECIALIST[key] ?? { mascot: "pilot" as MascotKey, label: readable(key) };
                  return (
                    <li key={key} className="flex items-start gap-3">
                      <Mascot kind={who.mascot} size={40} />
                      <div className="min-w-0 text-sm">
                        <p className="font-medium">{who.label}</p>
                        <p className="text-muted-foreground">{note}</p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="text-sm text-muted-foreground">No specialist notes. With no research model, the desk uses rules alone.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {desk?.scan && <ScanCard desk={desk} />}

      <TradeDeskCard desk={state?.desk?.trade_desk} />

      <Card>
        <CardHeader>
          <CardTitle>Run it now</CardTitle>
          <CardDescription>On the server these run on a schedule. You can also start them here; each runs once at a time.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <JobRunner kind="scan_overnight" label="1. Overnight scan of all F&O stocks" description="Positioning, delivery, large deals and upcoming events. Runs at 08:40." />
          <JobRunner kind="evidence" label="2. Collect news and announcements" />
          <JobRunner kind="scan_open" label="3. Open scan" description="Pre-open gap and strength against the Nifty. Run after 09:08; scheduled at 09:09." />
          <JobRunner kind="report" label="4. Agents and judge: build the report" />
          <JobRunner kind="report_email" label="Build and email the report" />
          <JobRunner kind="scan_confirm" label="09:31 check of the picks" description="Volume against normal, VWAP and strength since the open. Unconfirmed picks are not entered." />
          <JobRunner kind="tournament" label="Re-run the strategy tournament" description={card ? `Last scorecard ${dateTime(card.as_of)}.` : undefined} />
        </CardContent>
      </Card>
    </div>
  );
}

const BUILDUP_TONE: Record<string, "success" | "warning" | "destructive" | "outline"> = {
  "long build-up": "success",
  "short covering": "success",
  "long unwinding": "warning",
  "short build-up": "destructive",
};

function signed(value: number | null | undefined, suffix = "%") {
  if (value === null || value === undefined) return "—";
  return `${value > 0 ? "+" : ""}${value.toFixed(2)}${suffix}`;
}

type Ranked = NonNullable<NonNullable<DeskState["report"]>["ranked"]>[number];

function filings(row: Ranked) {
  const parts: string[] = (row.setups ?? []).map((tag) => tag.replace(/_/g, " "));
  const insiders = row.insiders;
  if (insiders?.pledges) parts.push(`${insiders.pledges} pledge(s)`);
  else if (insiders && insiders.net_market_inr) parts.push(`insiders net ${insiders.net_market_inr > 0 ? "bought" : "sold"} ₹${(Math.abs(insiders.net_market_inr) / 1e7).toFixed(1)} cr`);
  const results = row.results;
  if (results && !results.unavailable && results.revenue_yoy_pct != null) parts.push(`revenue ${results.revenue_yoy_pct > 0 ? "+" : ""}${results.revenue_yoy_pct}% YoY`);
  return parts.join(" · ");
}

function ScanCard({ desk }: { desk: NonNullable<DeskState["report"]> }) {
  const scan = desk.scan!;
  const steps = [
    { label: "F&O stocks scanned", value: scan.scanned },
    { label: "Passed the filters", value: scan.passed },
    { label: "Given to the agents", value: desk.pool || desk.ranked?.length || 0 },
    { label: "Picked", value: desk.watching.length },
  ];
  const confirmation = desk.confirmation;
  return (
    <Card>
      <CardHeader className="flex-row items-start gap-4 space-y-0">
        <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <Radar className="size-5" />
        </span>
        <div className="min-w-0 flex-1">
          <CardTitle>Today's scan</CardTitle>
          <CardDescription className="mt-1">
            The desk chose these itself from every F&O stock, on signals that lead the open: futures positioning, delivery, large deals,
            upcoming events and the pre-open gap against the Nifty.
            {scan.stage !== "open" && " The open stage did not run, so this ranking uses overnight signals only."}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="grid gap-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {steps.map((step) => (
            <div key={step.label} className="rounded-lg bg-muted/60 p-3">
              <p className="text-xs text-muted-foreground">{step.label}</p>
              <p className="num mt-1 text-xl font-semibold">{step.value}</p>
            </div>
          ))}
        </div>
        {Object.keys(scan.dropped_by).length > 0 && (
          <p className="text-sm text-muted-foreground">
            Dropped overnight: {Object.entries(scan.dropped_by).map(([why, count]) => `${count} ${why}`).join(" · ")}
            {scan.dropped_at_open.length > 0 && ` · at the open: ${scan.dropped_at_open.map((s) => s.replace("NSE:", "")).join(", ")}`}
          </p>
        )}
        {desk.ranked && desk.ranked.length > 0 && (
          <Table>
            <thead>
              <tr>
                <Th>Stock</Th>
                <Th>Futures</Th>
                <Th>Delivery</Th>
                <Th>Pre-open gap</Th>
                <Th>Vs Nifty</Th>
                <Th>Next 5 days</Th>
                <Th>Chart · filings</Th>
                <Th>Score</Th>
                <Th>09:31 check</Th>
              </tr>
            </thead>
            <tbody>
              {desk.ranked.map((row) => {
                const check = confirmation?.[row.symbol];
                return (
                  <tr key={row.symbol} className={cn(row.watch && "bg-primary/5")}>
                    <Td className="font-medium">
                      {row.symbol.replace("NSE:", "")}
                      {row.watch && <Badge className="ml-2">Pick</Badge>}
                    </Td>
                    <Td>{row.buildup ? <Badge variant={BUILDUP_TONE[row.buildup] ?? "outline"}>{row.buildup}</Badge> : "—"}</Td>
                    <Td className="num">{row.delivery_pct != null ? `${row.delivery_pct.toFixed(0)}%` : "—"}</Td>
                    <Td className="num">{signed(row.gap_pct)}</Td>
                    <Td className={cn("num", (row.rs_pct ?? 0) > 0 ? "text-success" : (row.rs_pct ?? 0) < 0 ? "text-destructive" : "")}>{signed(row.rs_pct, " pp")}</Td>
                    <Td className="text-xs text-muted-foreground">{row.events.length ? row.events.map((event) => `${event.purpose} ${event.date}`).join("; ") : "none"}</Td>
                    <Td className="text-xs text-muted-foreground">{filings(row) || "—"}</Td>
                    <Td className="num">{row.score ?? "—"}</Td>
                    <Td>
                      {!row.watch ? (
                        "—"
                      ) : !check ? (
                        <span className="text-xs text-muted-foreground">at 09:31</span>
                      ) : check.confirmed ? (
                        <span className="inline-flex items-center gap-1 text-sm text-success"><CircleCheck className="size-4" /> {check.rvol}x volume</span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-sm text-destructive" title={check.reasons.join("; ")}><CircleX className="size-4" /> not entered</span>
                      )}
                    </Td>
                  </tr>
                );
              })}
            </tbody>
          </Table>
        )}
        {scan.notes.length > 0 && <p className="text-xs text-muted-foreground">{scan.notes.join(" · ")}</p>}
        <p className="text-xs text-muted-foreground">
          Positioning is the previous session's close; gap and strength are from today's pre-open. They describe how traders are positioned,
          not where prices will go.
        </p>
      </CardContent>
    </Card>
  );
}
