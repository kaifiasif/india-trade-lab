import { useData } from "@/lib/context";
import { dateTime, readable, rupees } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress, Table, Td, Th } from "@/components/ui/misc";
import { Mascot } from "@/mascots/Mascot";

interface ResearchCall {
  symbol?: string;
  rating?: string;
  decision?: string;
  conviction?: string;
  reasons?: string[];
}
interface ScoreRow {
  count: number;
  hit_rate_pct: number | null;
  mean_raw_return_pct: number;
  mean_alpha_pp: number | null;
}

export function ResearchPage() {
  const { state } = useData();
  const report = state?.research?.report ?? null;
  const calls = (report?.calls ?? []) as ResearchCall[];
  const memory = report?.memory as { scorecard?: { settled?: number; by_rating?: Record<string, ScoreRow>; notice?: string } } | undefined;
  const score = memory?.scorecard;
  const histories = state?.histories ?? [];
  const watchlist = state?.watchlist;
  const goal = report?.goal;

  return (
    <div className="grid gap-6">
      <Card>
        <CardHeader className="flex-row items-start gap-4 space-y-0">
          <Mascot kind="atlas" size={64} mood={report ? "idle" : "sleep"} entrance="pop" />
          <div className="min-w-0 flex-1">
            <CardTitle>Research reviews</CardTitle>
            <CardDescription className="mt-1">
              {report ? `As of ${dateTime(report.as_of)}${report.archived ? " · archived" : ""}` : "No research review recorded. Nothing is invented while the service is off."}
            </CardDescription>
          </div>
          {report?.status && <Badge variant="outline">{readable(report.status)}</Badge>}
        </CardHeader>
        <CardContent className="grid gap-3">
          {calls.length ? (
            calls.map((call, index) => (
              <div key={index} className="rounded-lg border p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-medium">{call.symbol}</p>
                  {call.rating && <Badge variant={call.rating === "Buy" ? "success" : call.rating === "Sell" ? "destructive" : "default"}>{call.rating}</Badge>}
                  <span className="text-sm capitalize text-muted-foreground">
                    {readable(call.decision)}
                    {call.conviction ? ` · ${call.conviction} conviction` : ""}
                  </span>
                </div>
                {call.reasons?.length ? <p className="mt-2 text-sm text-muted-foreground">{call.reasons.join(" · ")}</p> : null}
              </div>
            ))
          ) : (
            report && <p className="text-sm text-muted-foreground">No current proposals.</p>
          )}
          {goal && (
            <p className="text-xs text-muted-foreground">
              Daily goal {rupees(goal.daily_target_inr)} · recorded today {rupees(goal.realized_today_inr)}. The goal never changes risk or quantity.
            </p>
          )}
        </CardContent>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>How past ratings did</CardTitle>
            <CardDescription>Each rated call is scored once its holding window closes in stored history.</CardDescription>
          </CardHeader>
          <CardContent>
            {score?.settled && score.by_rating ? (
              <div className="grid gap-3 sm:grid-cols-3">
                {Object.entries(score.by_rating).map(([rating, row]) => (
                  <div key={rating} className="rounded-lg bg-muted/60 p-3">
                    <p className="text-sm font-medium">
                      {rating} <span className="text-xs font-normal text-muted-foreground">· {row.count} settled</span>
                    </p>
                    <p className="num mt-1 text-xl font-semibold">{row.hit_rate_pct === null ? "—" : `${row.hit_rate_pct}%`}</p>
                    <p className="num text-xs text-muted-foreground">
                      mean {row.mean_raw_return_pct}%{row.mean_alpha_pp === null ? "" : ` · ${row.mean_alpha_pp} pp vs index`}
                    </p>
                  </div>
                ))}
                {score.notice && <p className="text-xs text-muted-foreground sm:col-span-3">{score.notice}</p>}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">No rated call has settled yet.</p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>History coverage</CardTitle>
            <CardDescription>Strategies are tested only once a stock has enough complete sessions.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-4">
            {histories.length ? (
              histories.map((item) => (
                <div key={item.symbol}>
                  <div className="flex items-baseline justify-between text-sm">
                    <span className="font-medium">{item.symbol}</span>
                    <span className="num text-muted-foreground">
                      {item.completed_sessions} / {item.minimum_sessions}
                    </span>
                  </div>
                  <Progress value={Math.min(100, (item.completed_sessions / Math.max(1, item.minimum_sessions)) * 100)} className="mt-1.5" />
                  <p className="mt-1 text-xs text-muted-foreground">{item.history_ready ? "Ready" : item.reason}</p>
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">No history loaded. Use Setup → Load history.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Screened watchlist</CardTitle>
          <CardDescription>{watchlist?.reason ?? "Ranked by liquidity and history from your chosen stocks."}</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <thead>
              <tr>
                <Th>Rank</Th>
                <Th>Stock</Th>
                <Th>Why</Th>
                <Th>Sessions</Th>
                <Th>Last session</Th>
              </tr>
            </thead>
            <tbody>
              {watchlist?.candidates?.length ? (
                watchlist.candidates.map((item) => (
                  <tr key={item.symbol}>
                    <Td className="num">{item.rank}</Td>
                    <Td className="font-medium">{item.symbol}</Td>
                    <Td className="text-muted-foreground">{item.reason}</Td>
                    <Td className="num">{item.history_sessions}</Td>
                    <Td>{item.last_session}</Td>
                  </tr>
                ))
              ) : (
                <tr>
                  <Td colSpan={5} className="py-8 text-center text-muted-foreground">
                    No candidates yet.
                  </Td>
                </tr>
              )}
            </tbody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
