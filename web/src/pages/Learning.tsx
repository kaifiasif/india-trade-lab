import { useCallback, useState } from "react";
import { BookOpenCheck, Snowflake } from "lucide-react";
import { get } from "@/lib/api";
import { usePoll } from "@/lib/hooks";
import type { LearningSummary, TrackRecord } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress, Skeleton, Table, Td, Th } from "@/components/ui/misc";
import { JobRunner } from "@/components/setup-kit";
import { Mascot, type Mood } from "@/mascots/Mascot";
import type { MascotKey } from "@/mascots/data";

const ROLES: { role: string; mascot: MascotKey; label: string }[] = [
  { role: "news-analyst", mascot: "scoop", label: "News" },
  { role: "sentiment-analyst", mascot: "vibe", label: "Sentiment" },
  { role: "technical-analyst", mascot: "chartly", label: "Technicals" },
  { role: "sector-analyst", mascot: "atlas", label: "Sector" },
  { role: "liquidity-analyst", mascot: "tide", label: "Liquidity" },
  { role: "brokerage-analyst", mascot: "ledger", label: "Brokerage views" },
  { role: "risk-scout", mascot: "scout", label: "Risk scout" },
  { role: "setup-planner", mascot: "blueprint", label: "Setup planner" },
  { role: "selection-judge", mascot: "judge", label: "Judge" },
];
const BY_ROLE = Object.fromEntries(ROLES.map((item) => [item.role, item]));

function moodOf(record?: TrackRecord): Mood {
  if (!record || record.graded < 5) return "idle";
  if (record.accuracy >= 0.6) return "happy";
  if (record.accuracy < 0.45) return "alert";
  return "thinking";
}

function ReportCard({ role, mascot, label, record }: { role: string; mascot: MascotKey; label: string; record?: TrackRecord }) {
  return (
    <div className="flex items-center gap-3 rounded-lg border p-3">
      <Mascot kind={mascot} size={52} mood={moodOf(record)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-sm font-medium">{label}</p>
          <p className="num text-lg font-semibold">{record ? `${Math.round(record.accuracy * 100)}%` : "—"}</p>
        </div>
        {record ? (
          <>
            <Progress value={record.accuracy * 100} className="mt-1.5 h-1.5" />
            <p className="num mt-1.5 text-xs text-muted-foreground">
              {record.right} right · {record.wrong} wrong{record.missed ? ` · ${record.missed} missed` : ""} · last {record.graded}
            </p>
          </>
        ) : (
          <p className="mt-1 text-xs text-muted-foreground">No graded calls yet</p>
        )}
      </div>
      <span className="sr-only">{role}</span>
    </div>
  );
}

export function LearningPage() {
  const fetcher = useCallback(() => get<LearningSummary>("/api/setup/learning"), []);
  const { data } = usePoll(fetcher, 15_000);
  const [allLessons, setAllLessons] = useState(false);
  if (!data) return <Skeleton className="h-96" />;
  const totals = data.totals ?? {};
  const graded = (totals.right ?? 0) + (totals.wrong ?? 0) + (totals.missed ?? 0);
  const usage = data.routing.usage;

  return (
    <div className="grid gap-6">
      <section className="flex flex-col gap-5 rounded-xl border bg-card p-5 sm:flex-row sm:items-center sm:p-6">
        <Mascot kind="echo" size={96} mood={graded ? "happy" : "thinking"} entrance="pop" />
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-semibold tracking-tight">How the desk learns</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Every evening each agent's calls are checked against what the stock then did and against the paper trades. Mistakes become short
            lessons that the agent reads the next morning; specialists who are right more often count for more; a stock that keeps losing sits
            out for a week. Lessons are used only after their outcome is known, and none of this can raise risk or add a trade.
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-sm">
            <Badge variant="outline">{data.sessions_graded} sessions graded</Badge>
            <Badge variant="success">{totals.right ?? 0} right</Badge>
            <Badge variant="destructive">{totals.wrong ?? 0} wrong</Badge>
            <Badge variant="warning">{totals.missed ?? 0} missed</Badge>
          </div>
        </div>
      </section>

      <Card>
        <CardHeader>
          <CardTitle>Report cards</CardTitle>
          <CardDescription>Accuracy over each agent's last 40 graded calls. Moves under 0.3% grade nobody; neutral views are not graded.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {ROLES.map((item) => (
            <ReportCard key={item.role} {...item} record={data.track_records[item.role]} />
          ))}
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>Recent lessons</CardTitle>
            <CardDescription>Written from each mistake. The agent named sees its own, newest first.</CardDescription>
          </CardHeader>
          <CardContent>
            {data.lessons.length ? (
              <ul className="grid gap-3">
                {data.lessons.slice(0, allLessons ? 25 : 6).map((lesson, index) => {
                  const who = BY_ROLE[lesson.subject];
                  return (
                    <li key={index} className="flex gap-3">
                      {lesson.kind === "cooldown" ? (
                        <span className="grid size-10 shrink-0 place-items-center rounded-full bg-primary/10 text-primary">
                          <Snowflake className="size-4" />
                        </span>
                      ) : (
                        <Mascot kind={who?.mascot ?? "echo"} size={40} />
                      )}
                      <div className="min-w-0 text-sm">
                        <p className="flex flex-wrap items-center gap-2 font-medium">
                          {who?.label ?? lesson.subject.replace("NSE:", "")}
                          <Badge variant={lesson.kind === "wrong" ? "destructive" : lesson.kind === "missed" ? "warning" : "default"}>{lesson.kind}</Badge>
                        </p>
                        <p className="text-muted-foreground">{lesson.text}</p>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : null}
            {data.lessons.length > 6 && (
              <Button variant="ghost" size="sm" className="mt-3" onClick={() => setAllLessons((value) => !value)}>
                {allLessons ? "Show fewer" : `Show all ${data.lessons.length}`}
              </Button>
            )}
            {!data.lessons.length && (
              <p className="flex items-center gap-2 text-sm text-muted-foreground">
                <BookOpenCheck className="size-4" /> No mistakes recorded yet. Lessons appear after the first evening grading.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Model use today</CardTitle>
            <CardDescription>{data.routing.enabled ? "Calls and tokens per tier against the limits you set." : "Smart routing is off. Turn it on in Setup → Research model."}</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {usage.length ? (
              usage.map((tier) => {
                const share = tier.requests_per_day ? Math.min(100, (tier.requests / tier.requests_per_day) * 100) : 0;
                return (
                  <div key={tier.tier}>
                    <div className="flex items-baseline justify-between gap-2 text-sm">
                      <span className="font-medium capitalize">
                        {tier.tier} <span className="font-mono text-xs font-normal text-muted-foreground">{tier.model}</span>
                      </span>
                      <span className="num text-muted-foreground">
                        {tier.requests}
                        {tier.requests_per_day ? ` / ${tier.requests_per_day}` : ""} calls
                      </span>
                    </div>
                    {tier.requests_per_day > 0 && <Progress value={share} className={cn("mt-1.5 h-1.5", share > 85 && "[&>div]:bg-warning")} />}
                    <p className="num mt-1 text-xs text-muted-foreground">
                      {tier.tokens.toLocaleString("en-IN")} tokens
                      {Object.entries(tier.outcomes)
                        .filter(([key]) => key !== "ok")
                        .map(([key, value]) => ` · ${value} ${key.replace("_", " ")}`)
                        .join("")}
                    </p>
                  </div>
                );
              })
            ) : (
              <p className="text-sm text-muted-foreground">No routed calls today.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>What the desk knows about each stock</CardTitle>
          <CardDescription>Built from the last 60 sessions and the desk's own record. The agents read this as a note.</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <thead>
              <tr>
                <Th>Stock</Th>
                <Th>Daily range</Th>
                <Th>Average gap</Th>
                <Th>Up days</Th>
                <Th>Judge picks</Th>
                <Th>Paper trades</Th>
                <Th>Status</Th>
              </tr>
            </thead>
            <tbody>
              {data.stock_notes.length ? (
                data.stock_notes.map((note) => (
                  <tr key={note.symbol}>
                    <Td className="font-medium">{note.symbol.replace("NSE:", "")}</Td>
                    <Td className="num">{note.avg_range_pct !== undefined ? `${note.avg_range_pct}%` : "—"}</Td>
                    <Td className="num">{note.avg_abs_gap_pct !== undefined ? `${note.avg_abs_gap_pct}%` : "—"}</Td>
                    <Td className="num">{note.up_close_share !== undefined ? `${Math.round(note.up_close_share * 100)}%` : "—"}</Td>
                    <Td className="num">{note.judge_picks_graded ? `${note.judge_picks_right}/${note.judge_picks_graded} right` : "—"}</Td>
                    <Td className="num">
                      {note.paper_trades ? `${note.paper_wins}/${note.paper_trades} won${note.avg_r != null ? ` · ${note.avg_r > 0 ? "+" : ""}${note.avg_r.toFixed(2)}R` : ""}` : "—"}
                    </Td>
                    <Td>{note.cooldown_until ? <Badge variant="warning" title={note.cooldown_reason}>Cooling down to {note.cooldown_until}</Badge> : <Badge variant="outline">Active</Badge>}</Td>
                  </tr>
                ))
              ) : (
                <tr>
                  <Td colSpan={7} className="py-8 text-center text-muted-foreground">
                    No stock notes yet.
                  </Td>
                </tr>
              )}
            </tbody>
          </Table>
        </CardContent>
      </Card>

      <div className="grid gap-6 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Fine-tuning</CardTitle>
            <CardDescription>
              Not needed while the lessons work. It is worth trying for a role only when it has enough right answers to learn from and its accuracy
              stays low. The export never uploads anything.
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            <ul className="grid gap-2 text-sm">
              {data.finetune.map((item) => (
                <li key={item.role} className="flex flex-wrap items-baseline justify-between gap-x-3 border-b pb-2 last:border-0">
                  <span className="font-medium">{BY_ROLE[item.role]?.label ?? item.role}</span>
                  <span className={cn("text-xs text-muted-foreground", item.advice.startsWith("Worth") && "font-medium text-primary")}>{item.advice}</span>
                </li>
              ))}
            </ul>
            <JobRunner kind="finetune_export" label="Export training data" description="Writes train and eval JSONL for every role with right answers to data/observatory/finetune/." />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Run the grading now</CardTitle>
            <CardDescription>On the server this runs every evening after the history sync and the tournament.</CardDescription>
          </CardHeader>
          <CardContent>
            <JobRunner kind="learn" label="Grade the agents and learn" />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
