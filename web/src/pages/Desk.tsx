import { CircleSlash, ShieldAlert } from "lucide-react";
import { useData } from "@/lib/context";
import { dateTime, readable } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/misc";
import { JobRunner } from "@/components/setup-kit";
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

      <Card>
        <CardHeader>
          <CardTitle>Run it now</CardTitle>
          <CardDescription>On the server these run on a schedule. You can also start them here; each runs once at a time.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3">
          <JobRunner kind="evidence" label="Collect news and announcements" />
          <JobRunner kind="report" label="Build the pre-market report" />
          <JobRunner kind="report_email" label="Build and email the report" />
          <JobRunner kind="tournament" label="Re-run the strategy tournament" description={card ? `Last scorecard ${dateTime(card.as_of)}.` : undefined} />
        </CardContent>
      </Card>
    </div>
  );
}
