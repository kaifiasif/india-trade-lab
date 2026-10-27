import { useCallback, useEffect, useMemo, useState } from "react";
import { Loader2, RotateCcw, Save } from "lucide-react";
import { ApiError, get, setup } from "@/lib/api";
import { useData } from "@/lib/context";
import { toast } from "@/lib/toast";
import { cn, readable } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Textarea } from "@/components/ui/input";
import { Field, Skeleton } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { explain } from "@/components/setup-kit";

type Value = unknown;
interface View {
  version: string;
  settings: Record<string, Value>;
  mode: string;
}

const SECTIONS: { id: string; label: string; note: string; keys: string[] }[] = [
  { id: "desk", label: "Desk", note: "How many stocks the desk looks at and how it screens them.", keys: ["max_candidates", "screening_mode", "review_workflow", "poll_seconds", "min_turnover_inr", "target_r", "daily_profit_goal_inr", "min_scored_headlines"] },
  { id: "costs", label: "Costs", note: "Used in every paper fill and in the tournament (which doubles them).", keys: ["fee_bps", "fee_flat_inr", "slippage_bps"] },
  { id: "model", label: "Research model", note: "API keys are set in Setup and never shown here.", keys: ["model_provider", "model", "quick_model", "deep_model", "reasoning_effort", "max_model_calls_per_day", "model_timeout_seconds", "max_output_tokens", "local_base_url", "local_timeout_seconds", "model_routes"] },
  { id: "email", label: "Email", note: "The app password is set in Setup → Email and never shown here.", keys: ["smtp_host", "smtp_port", "smtp_user", "email_from", "email_to"] },
  { id: "strategy", label: "Strategies", note: "Which strategies may compete, and how they exit.", keys: ["strategy", "autopilot"] },
  { id: "agents", label: "Agents", note: "Debate, memory and the selection judge.", keys: ["selection", "debate", "memory", "market_feeds"] },
];

const LABELS: Record<string, [string, string?]> = {
  max_candidates: ["Stocks to assess each day", "1 to 3."],
  screening_mode: ["Screening", "Liquidity ranks by turnover; relative strength by move versus the index."],
  review_workflow: ["Agent workflow", "Debate adds a bull and bear round per stock."],
  poll_seconds: ["Check prices every (seconds)"],
  min_turnover_inr: ["Minimum daily turnover (₹)", "Thinner stocks are skipped: fills would not be realistic."],
  target_r: ["Target, in multiples of risk", "2 means the target is twice the stop distance."],
  daily_profit_goal_inr: ["Daily goal (₹)", "Shown for reference only. It never changes risk or size."],
  min_scored_headlines: ["Headlines needed for a news view"],
  fee_bps: ["Fees (basis points per side)"],
  fee_flat_inr: ["Flat fee per order (₹)"],
  slippage_bps: ["Slippage (basis points)"],
  model_provider: ["Provider"],
  model: ["Model"],
  quick_model: ["Quick model", "Optional cheaper model for simple steps."],
  deep_model: ["Deep model", "Optional stronger model for the judge."],
  reasoning_effort: ["Reasoning effort"],
  max_model_calls_per_day: ["Most model calls per day", "A hard budget; the desk falls back to rules after it."],
  model_timeout_seconds: ["Model timeout (seconds)"],
  max_output_tokens: ["Longest answer (tokens)"],
  local_base_url: ["Local server address", "Loopback only, e.g. http://127.0.0.1:11434/v1."],
  local_timeout_seconds: ["Local timeout (seconds)"],
  smtp_host: ["SMTP server", "smtp.gmail.com for Gmail."],
  smtp_port: ["SMTP port", "587 with STARTTLS."],
  smtp_user: ["Send from (login)"],
  email_from: ["From address shown", "Leave empty to use the login."],
  email_to: ["Send the report to", "Comma-separated, up to five."],
  market_feeds: ["Extra news feeds (RSS URLs)", "Up to five, comma-separated."],
};

const CHOICES: Record<string, string[]> = {
  screening_mode: ["liquidity", "relative_strength"],
  review_workflow: ["intraday", "intraday_debate"],
  model_provider: ["disabled", "gemini", "anthropic", "openai", "local"],
  reasoning_effort: ["low", "medium", "high"],
};

const same = (a: Value, b: Value) => JSON.stringify(a) === JSON.stringify(b);

function Control({ name, value, onChange, path }: { name: string; value: Value; onChange: (next: Value) => void; path: string }) {
  const id = `setting-${path}`;
  const [label, hint] = LABELS[name] ?? [readable(name).replace(/^./, (c) => c.toUpperCase())];
  if (typeof value === "boolean") {
    return (
      <div className="flex items-center justify-between gap-4 rounded-md border px-3 py-2.5">
        <label htmlFor={id} className="text-sm">
          {label}
          {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
        </label>
        <Switch id={id} checked={value} onCheckedChange={onChange} />
      </div>
    );
  }
  if (CHOICES[name] && typeof value === "string") {
    return (
      <Field label={label} hint={hint}>
        <Select value={value} onValueChange={onChange}>
          <SelectTrigger aria-label={label} id={id}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CHOICES[name].map((choice) => (
              <SelectItem key={choice} value={choice}>
                {readable(choice)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
    );
  }
  if (typeof value === "number") {
    return (
      <Field label={label} hint={hint} htmlFor={id}>
        <Input id={id} inputMode="decimal" className="num" value={String(value)} onChange={(event) => onChange(event.target.value === "" ? 0 : Number(event.target.value.replace(/[^0-9.-]/g, "")))} />
      </Field>
    );
  }
  if (typeof value === "string") {
    return (
      <Field label={label} hint={hint} htmlFor={id}>
        <Input id={id} value={value} onChange={(event) => onChange(event.target.value)} className={/url|host|model/.test(name) ? "font-mono" : undefined} />
      </Field>
    );
  }
  if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
    return (
      <Field label={label} hint={hint} htmlFor={id}>
        <Input id={id} value={value.join(", ")} onChange={(event) => onChange(event.target.value.split(",").map((item) => item.trim()).filter(Boolean))} />
      </Field>
    );
  }
  if (value && typeof value === "object" && !Array.isArray(value)) {
    const entries = Object.entries(value as Record<string, Value>);
    const simple = entries.every(([, item]) => item === null || ["boolean", "number", "string"].includes(typeof item) || (Array.isArray(item) && item.every((x) => typeof x === "string")));
    if (simple) {
      return (
        <fieldset className="grid gap-3 rounded-lg border p-4">
          <legend className="px-1 text-sm font-medium">{label}</legend>
          {hint && <p className="-mt-1 text-xs text-muted-foreground">{hint}</p>}
          <div className="grid gap-3 sm:grid-cols-2">
            {entries.map(([key, item]) => (
              <Control key={key} name={key} path={`${path}-${key}`} value={item} onChange={(next) => onChange({ ...(value as object), [key]: next })} />
            ))}
          </div>
        </fieldset>
      );
    }
  }
  return <JsonControl id={id} label={label} hint={hint} value={value} onChange={onChange} />;
}

function JsonControl({ id, label, hint, value, onChange }: { id: string; label: string; hint?: string; value: Value; onChange: (next: Value) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value, null, 2));
  const [error, setError] = useState<string | undefined>();
  useEffect(() => {
    setText(JSON.stringify(value, null, 2));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(value)]);
  return (
    <Field label={label} hint={hint ?? "JSON"} htmlFor={id} error={error}>
      <Textarea
        id={id}
        rows={Math.min(14, text.split("\n").length + 1)}
        className="font-mono text-xs"
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          try {
            onChange(JSON.parse(event.target.value));
            setError(undefined);
          } catch {
            setError("Not valid JSON yet");
          }
        }}
      />
    </Field>
  );
}

export function SettingsPage() {
  const { refreshSetup, setup: status } = useData();
  const [view, setView] = useState<View | null>(null);
  const [draft, setDraft] = useState<Record<string, Value>>({});
  const [errors, setErrors] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [missing, setMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      const next = await get<View>("/api/setup/settings");
      setView(next);
      setDraft(next.settings);
      setMissing(false);
    } catch (error) {
      if (error instanceof ApiError && error.code === "project_required") setMissing(true);
      else toast.error("Settings not loaded", explain(error));
    }
  }, []);
  useEffect(() => {
    load();
  }, [load, status?.config_exists]);

  const changes = useMemo(() => {
    if (!view) return {};
    return Object.fromEntries(Object.entries(draft).filter(([key, value]) => !same(value, view.settings[key])));
  }, [draft, view]);
  const changed = Object.keys(changes);

  async function save() {
    if (!view || !changed.length) return;
    setSaving(true);
    setErrors(null);
    try {
      const next = await setup<View>("save_settings", { version: view.version, changes });
      setView(next);
      setDraft(next.settings);
      await refreshSetup();
      toast.success("Settings saved", `${changed.length} change${changed.length === 1 ? "" : "s"}. A backup of the previous file was kept.`);
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        toast.error("Settings changed elsewhere", "Reloaded the latest version. Make your change again.");
        await load();
      } else {
        setErrors(explain(error));
      }
    } finally {
      setSaving(false);
    }
  }

  if (missing) {
    return (
      <Card>
        <CardContent className="p-6 text-sm text-muted-foreground">
          Create the project in{" "}
          <a href="#/setup?step=project" className="text-primary underline-offset-4 hover:underline">
            Setup
          </a>{" "}
          first.
        </CardContent>
      </Card>
    );
  }
  if (!view) return <Skeleton className="h-96" />;

  return (
    <div className="grid gap-6 pb-24">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-2xl">
          <h2 className="text-xl font-semibold tracking-tight">Settings</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Every save is checked by the same validation the desk runs at startup, then written atomically with a backup. The mode is always paper
            research; nothing here can enable real orders.
          </p>
        </div>
        <Badge variant="outline">Mode: {readable(view.mode)}</Badge>
      </div>
      <Tabs defaultValue="desk" className="grid gap-4">
        <TabsList className="w-full justify-start overflow-x-auto sm:w-fit">
          {SECTIONS.map((section) => {
            const dirty = section.keys.some((key) => key in changes);
            return (
              <TabsTrigger key={section.id} value={section.id} className="gap-1.5">
                {section.label}
                {dirty && <span className="size-1.5 rounded-full bg-primary" aria-label="unsaved" />}
              </TabsTrigger>
            );
          })}
        </TabsList>
        {SECTIONS.map((section) => (
          <TabsContent key={section.id} value={section.id}>
            <Card>
              <CardHeader>
                <CardTitle>{section.label}</CardTitle>
                <CardDescription>{section.note}</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 md:grid-cols-2">
                {section.keys
                  .filter((key) => key in draft)
                  .map((key) => (
                    <div key={key} className={cn(typeof draft[key] === "object" && draft[key] !== null && !Array.isArray(draft[key]) && "md:col-span-2")}>
                      <Control name={key} path={key} value={draft[key]} onChange={(next) => setDraft({ ...draft, [key]: next })} />
                    </div>
                  ))}
              </CardContent>
            </Card>
          </TabsContent>
        ))}
      </Tabs>

      <div
        className={cn(
          "fixed inset-x-0 bottom-0 z-30 border-t bg-card/95 backdrop-blur transition-transform lg:left-64",
          changed.length ? "translate-y-0" : "translate-y-full",
        )}
        aria-hidden={!changed.length}
      >
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3 sm:px-6">
          <p className="text-sm">
            <span className="font-medium">{changed.length} unsaved</span>
            <span className="text-muted-foreground"> · {changed.map((key) => LABELS[key]?.[0] ?? readable(key)).join(", ")}</span>
          </p>
          {errors && <p className="basis-full text-sm text-destructive sm:order-last">{errors}</p>}
          <div className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={() => setDraft(view.settings)} disabled={saving} tabIndex={changed.length ? 0 : -1}>
              <RotateCcw /> Discard
            </Button>
            <Button onClick={save} disabled={saving} tabIndex={changed.length ? 0 : -1}>
              {saving ? <Loader2 className="animate-spin" /> : <Save />} Save changes
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
