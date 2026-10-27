import { useState } from "react";
import { MASCOTS, type MascotKey } from "@/mascots/data";
import { Mascot, type Mood } from "@/mascots/Mascot";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

const GROUPS: { title: string; note: string; members: { key: MascotKey; does: string }[] }[] = [
  {
    title: "Specialists",
    note: "Read the evidence for each stock and give one view each. Advice only.",
    members: [
      { key: "scoop", does: "Reads company news and exchange announcements." },
      { key: "vibe", does: "Weighs the tone of headlines, not just the count." },
      { key: "chartly", does: "Checks trend, RSI and the setup on the chart." },
      { key: "atlas", does: "Compares the stock with its sector today." },
      { key: "tide", does: "Checks turnover, spreads and whether fills are realistic." },
      { key: "ledger", does: "Summarises what brokerages have said recently." },
    ],
  },
  {
    title: "Sub-agents",
    note: "Called by the specialists when a pick needs a second look.",
    members: [
      { key: "scout", does: "Looks for reasons not to trade: events, gaps, surveillance." },
      { key: "blueprint", does: "Drafts where entry, stop and target would sit." },
    ],
  },
  {
    title: "Decision",
    note: "Narrows the list. Can drop a stock, never add risk.",
    members: [
      { key: "judge", does: "Picks at most a few stocks to watch, or sits the day out." },
      { key: "bullu", does: "Argues the case for, in debate mode." },
      { key: "bruno", does: "Argues the case against, in debate mode." },
      { key: "captain", does: "Balances the book across picks." },
    ],
  },
  {
    title: "Code (not AI)",
    note: "Rules that no agent can override.",
    members: [
      { key: "shield", does: "Sizes every trade from your limits and blocks anything over them." },
      { key: "ref", does: "Runs the strategy tournament at double costs." },
      { key: "pilot", does: "Watches picks in market hours and keeps the paper book." },
      { key: "echo", does: "Writes the sealed journal and learns from settled calls." },
    ],
  },
];

const MOODS: Mood[] = ["wave", "happy", "thinking", "alert", "sleep", "idle"];

function Member({ kind, does, delay }: { kind: MascotKey; does: string; delay: number }) {
  const [mood, setMood] = useState<Mood>("idle");
  const spec = MASCOTS[kind];
  return (
    <Card className="group overflow-hidden">
      <CardContent className="flex items-center gap-4 p-4">
        <button
          className="shrink-0 rounded-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          onClick={() => setMood(MOODS[(MOODS.indexOf(mood) + 1) % MOODS.length])}
          aria-label={`Change ${spec.name}'s mood (now ${mood})`}
        >
          <Mascot kind={kind} size={84} mood={mood} entrance="walk" delay={delay / 1000} />
        </button>
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="font-semibold">{spec.name}</p>
            <span className="size-2 rounded-full" style={{ background: spec.accent }} aria-hidden />
          </div>
          <p className="text-xs capitalize text-muted-foreground">{spec.role.replaceAll("-", " ")}</p>
          <p className="mt-1.5 text-sm">{does}</p>
        </div>
      </CardContent>
    </Card>
  );
}

export function AgentsPage() {
  let index = 0;
  return (
    <div className="grid gap-8">
      <div className="max-w-3xl">
        <h2 className="text-xl font-semibold tracking-tight">Meet the desk</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Sixteen members, each with one job. The AI agents advise and narrow; the code members size, block and record. None of them can place a
          real order. Tap a robot to change its mood.
        </p>
      </div>
      {GROUPS.map((group) => (
        <section key={group.title} className="grid gap-3">
          <div className="flex flex-wrap items-baseline gap-3">
            <h3 className="font-semibold">{group.title}</h3>
            <Badge variant="outline">{group.members.length}</Badge>
            <p className="text-sm text-muted-foreground">{group.note}</p>
          </div>
          <div className={cn("grid gap-3 sm:grid-cols-2 xl:grid-cols-3")}>
            {group.members.map((member) => (
              <Member key={member.key} kind={member.key} does={member.does} delay={index++ * 60} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
