import { useEffect, useRef, useState } from "react";
import { Check, ExternalLink, FileUp, Loader2, Lock, Mail, Search, ShieldCheck, X } from "lucide-react";
import { get, setup } from "@/lib/api";
import { useData } from "@/lib/context";
import { useRoute } from "@/lib/hooks";
import { toast } from "@/lib/toast";
import { cn, dateTime, rupees } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Field, Progress } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { JobRunner, SecretField, explain } from "@/components/setup-kit";
import { RoutingEditor } from "@/components/RoutingEditor";
import { Mascot, type Mood } from "@/mascots/Mascot";
import type { MascotKey } from "@/mascots/data";
import { Confetti } from "@/mascots/Confetti";

const GUIDE: Record<string, MascotKey> = {
  project: "blueprint",
  profile: "pilot",
  kite_keys: "shield",
  kite_login: "shield",
  email: "echo",
  model: "judge",
  stocks: "scout",
  history: "tide",
  tournament: "ref",
  book: "ledger",
  attest: "captain",
};

/** Save a few settings with the version the server last gave us. */
async function saveSettings(changes: Record<string, unknown>) {
  const view = await get<{ version: string }>("/api/setup/settings");
  return setup("save_settings", { version: view.version, changes });
}

function useBusy() {
  const [busy, setBusy] = useState<string | null>(null);
  async function run<T>(name: string, work: () => Promise<T>): Promise<T | undefined> {
    setBusy(name);
    try {
      return await work();
    } finally {
      setBusy(null);
    }
  }
  return { busy, run };
}

function Done({ children }: { children: React.ReactNode }) {
  return (
    <p className="flex items-center gap-2 rounded-md bg-success/10 px-3 py-2 text-sm text-success">
      <Check className="size-4" /> {children}
    </p>
  );
}

// ---------- steps ----------

function ProjectStep() {
  const { setup: status, refreshSetup } = useData();
  const { busy, run } = useBusy();
  return (
    <div className="grid gap-4">
      <p className="text-sm text-muted-foreground">
        Creates <code className="font-mono text-foreground">pipeline.json</code> and the NSE 2026 calendar in the private data folder. Nothing is
        overwritten if it already exists. The project is fixed to paper research mode.
      </p>
      {status?.config_exists ? (
        <Done>The project exists.</Done>
      ) : (
        <Button
          className="w-fit"
          disabled={busy !== null}
          onClick={() =>
            run("init", async () => {
              try {
                await setup("init_project");
                await refreshSetup();
                toast.success("Project created");
              } catch (error) {
                toast.error("Could not create the project", explain(error));
              }
            })
          }
        >
          {busy && <Loader2 className="animate-spin" />} Create the project
        </Button>
      )}
    </div>
  );
}

function ProfileStep() {
  const { setup: status, refreshSetup } = useData();
  const settings = status?.settings ?? {};
  const [name, setName] = useState(status?.profile?.name ?? "");
  const savedTo = settings.email_to;
  const [to, setTo] = useState(Array.isArray(savedTo) ? savedTo.join(", ") : String(savedTo ?? ""));
  const [from, setFrom] = useState(String(settings.email_from ?? ""));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const { busy, run } = useBusy();
  return (
    <form
      className="grid max-w-lg gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        run("profile", async () => {
          try {
            await setup("save_profile", { name, email_to: to.split(",").map((item) => item.trim()).filter(Boolean), email_from: from.trim() });
            setErrors({});
            await refreshSetup();
            toast.success("Details saved");
          } catch (error) {
            setErrors((error as { errors?: Record<string, string> }).errors ?? {});
            toast.error("Could not save your details", explain(error));
          }
        });
      }}
    >
      <Field label="Your name" htmlFor="name" error={errors.name}>
        <Input id="name" value={name} onChange={(event) => setName(event.target.value)} autoComplete="name" maxLength={80} />
      </Field>
      <Field label="Send the morning report to" htmlFor="to" hint="Up to five addresses, separated by commas." error={errors.email_to}>
        <Input id="to" type="text" inputMode="email" value={to} onChange={(event) => setTo(event.target.value)} autoComplete="email" />
      </Field>
      <Field label="Send from (optional)" htmlFor="from" hint="Leave empty to send from the Gmail account you connect." error={errors.email_from}>
        <Input id="from" type="email" value={from} onChange={(event) => setFrom(event.target.value)} />
      </Field>
      <Button type="submit" className="w-fit" disabled={busy !== null}>
        {busy && <Loader2 className="animate-spin" />} Save details
      </Button>
    </form>
  );
}

function KiteKeysStep() {
  return (
    <div className="grid max-w-lg gap-5">
      <p className="text-sm text-muted-foreground">
        Create a Kite Connect app at{" "}
        <a className="text-primary underline-offset-4 hover:underline" href="https://developers.kite.trade/apps" target="_blank" rel="noreferrer">
          developers.kite.trade <ExternalLink className="inline size-3" />
        </a>
        . Set its redirect URL to <code className="font-mono text-foreground">http://127.0.0.1</code>. This lab only reads market data; it has no
        code that places orders.
      </p>
      <SecretField name="KITE_API_KEY" label="API key" placeholder="e.g. abcd1234efgh5678" />
      <SecretField name="KITE_API_SECRET" label="API secret" hint="Stored in a file only your user can read. It is never shown again or sent back to this page." />
    </div>
  );
}

function KiteLoginStep() {
  const { setup: status, refreshSetup } = useData();
  const [pasted, setPasted] = useState("");
  const { busy, run } = useBusy();
  const token = status?.kite?.token;
  return (
    <div className="grid max-w-xl gap-5">
      {token?.today && <Done>Logged in today at {dateTime(token.saved_at)}. Kite tokens expire every morning around 06:00.</Done>}
      <ol className="grid gap-4 text-sm">
        <li className="flex gap-3">
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary">1</span>
          <div className="grid gap-2">
            <p>Open Zerodha's login page and finish 2FA.</p>
            <Button
              variant="outline"
              className="w-fit"
              disabled={!status?.kite?.api_key || busy !== null}
              onClick={() =>
                run("url", async () => {
                  try {
                    const { url } = await setup<{ url: string }>("kite_login_url");
                    window.open(url, "_blank", "noopener");
                  } catch (error) {
                    toast.error("Could not open the login", explain(error));
                  }
                })
              }
            >
              Open Zerodha login <ExternalLink />
            </Button>
          </div>
        </li>
        <li className="flex gap-3">
          <span className="grid size-6 shrink-0 place-items-center rounded-full bg-primary/10 text-xs font-semibold text-primary">2</span>
          <form
            className="grid flex-1 gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              run("exchange", async () => {
                try {
                  await setup("kite_exchange", { redirect_url: pasted.trim() });
                  setPasted("");
                  await refreshSetup();
                  toast.success("Kite login saved for today");
                } catch (error) {
                  toast.error("Login not saved", explain(error));
                }
              });
            }}
          >
            <label htmlFor="redirect" className="font-normal">
              Zerodha then opens a page that may not load. Copy that whole address from the browser bar and paste it here.
            </label>
            <div className="flex gap-2">
              <Input id="redirect" value={pasted} onChange={(event) => setPasted(event.target.value)} placeholder="http://127.0.0.1/?request_token=…&status=success" className="font-mono" autoComplete="off" />
              <Button type="submit" disabled={!pasted.trim() || busy !== null}>
                {busy === "exchange" && <Loader2 className="animate-spin" />} Save login
              </Button>
            </div>
          </form>
        </li>
      </ol>
      {!status?.kite?.api_key && <p className="text-sm text-warning">Save your Kite keys first.</p>}
    </div>
  );
}

const MAIL_SERVERS = [
  { id: "gmail", label: "Gmail", host: "smtp.gmail.com", port: 587, hint: "Use a 16-character app password from myaccount.google.com/apppasswords (needs 2-Step Verification). Not your Google password." },
  { id: "outlook", label: "Outlook / Microsoft 365", host: "smtp.office365.com", port: 587, hint: "Use an app password if your account has two-step verification." },
  { id: "zoho", label: "Zoho Mail", host: "smtp.zoho.in", port: 587, hint: "Use an application-specific password from Zoho's security settings." },
  { id: "other", label: "Other server", host: "", port: 587, hint: "Any mail server that supports STARTTLS on the port you give." },
];

function EmailStep() {
  const { setup: status, refreshSetup } = useData();
  const settings = status?.settings ?? {};
  const savedHost = String(settings.smtp_host ?? "");
  const [server, setServer] = useState(MAIL_SERVERS.find((item) => item.host && item.host === savedHost)?.id ?? (savedHost ? "other" : "gmail"));
  const preset = MAIL_SERVERS.find((item) => item.id === server) ?? MAIL_SERVERS[0];
  const [host, setHost] = useState(savedHost);
  const [port, setPort] = useState(String(settings.smtp_port ?? 587));
  const [user, setUser] = useState(String(settings.smtp_user ?? ""));
  const { busy, run } = useBusy();
  const email = status?.email;
  return (
    <div className="grid max-w-lg gap-5">
      <p className="text-sm text-muted-foreground">
        The morning report is sent from your own mailbox over SMTP. The app password goes into the private file on the server, never into
        pipeline.json, and this page cannot read it back.
      </p>
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          run("server", async () => {
            try {
              await saveSettings({ smtp_host: server === "other" ? host.trim() : preset.host, smtp_port: Number(server === "other" ? port : preset.port), smtp_user: user.trim() });
              await refreshSetup();
              toast.success("Mail server saved");
            } catch (error) {
              toast.error("Mail server not saved", explain(error));
            }
          });
        }}
      >
        <Field label="Your mail service" hint={preset.hint}>
          <Select value={server} onValueChange={setServer}>
            <SelectTrigger aria-label="Your mail service">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {MAIL_SERVERS.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {server === "other" && (
          <div className="grid gap-4 sm:grid-cols-[1fr_110px]">
            <Field label="SMTP server" htmlFor="smtp-host">
              <Input id="smtp-host" value={host} onChange={(event) => setHost(event.target.value)} placeholder="smtp.example.com" className="font-mono" required />
            </Field>
            <Field label="Port" htmlFor="smtp-port">
              <Input id="smtp-port" inputMode="numeric" value={port} onChange={(event) => setPort(event.target.value.replace(/\D/g, ""))} className="num" />
            </Field>
          </div>
        )}
        <Field label="Send from (your email address)" htmlFor="smtp-user">
          <Input id="smtp-user" type="email" value={user} onChange={(event) => setUser(event.target.value)} placeholder="you@gmail.com" autoComplete="email" required />
        </Field>
        <Button type="submit" variant="outline" className="w-fit" disabled={busy !== null}>
          {busy === "server" && <Loader2 className="animate-spin" />} Save mail server
        </Button>
      </form>
      <SecretField name="SMTP_PASSWORD" label="App password" placeholder="abcd efgh ijkl mnop" />
      <div className="flex flex-wrap items-center gap-3 border-t pt-4">
        <Button
          disabled={!(email?.server && email?.password) || busy !== null}
          onClick={() =>
            run("test", async () => {
              try {
                await setup("send_test_email");
                toast.success("Test email sent", "Check your inbox and the spam folder.");
              } catch (error) {
                toast.error("Test email failed", explain(error));
              }
            })
          }
        >
          {busy === "test" ? <Loader2 className="animate-spin" /> : <Mail />} Send a test email
        </Button>
        {!email?.recipients && <span className="text-xs text-warning">Add where to send the report in step 2 first.</span>}
      </div>
    </div>
  );
}

const PROVIDERS = [
  { id: "disabled", label: "None (rules only)", key: null, hint: "The desk still screens, sizes and journals; specialists and the judge are skipped." },
  { id: "openrouter", label: "OpenRouter (one key, the desk picks models)", key: "OPENROUTER_API_KEY", hint: "Key from openrouter.ai/keys. Free models do the simple jobs; a capped paid model judges." },
  { id: "gemini", label: "Google Gemini", key: "GEMINI_API_KEY", hint: "Has a free tier at aistudio.google.com." },
  { id: "anthropic", label: "Anthropic Claude", key: "ANTHROPIC_API_KEY", hint: "Key from console.anthropic.com." },
  { id: "openai", label: "OpenAI", key: "OPENAI_API_KEY", hint: "Key from platform.openai.com." },
  { id: "local", label: "Local server", key: "LOCAL_LLM_API_KEY", hint: "An OpenAI-compatible server on this machine. Set its address in Settings." },
];

function ModelStep() {
  const { setup: status, refreshSetup } = useData();
  const [provider, setProvider] = useState(status?.model?.provider ?? "disabled");
  const [model, setModel] = useState(String(status?.settings?.model ?? ""));
  const savedCaps = (status?.settings?.openrouter ?? {}) as { max_usd_per_day?: number };
  const [cap, setCap] = useState(String(savedCaps.max_usd_per_day ?? 0.5));
  const [freeOnly, setFreeOnly] = useState(savedCaps.max_usd_per_day === 0);
  const { busy, run } = useBusy();
  const chosen = PROVIDERS.find((item) => item.id === provider) ?? PROVIDERS[0];
  const auto = provider === "openrouter";
  const dollars = Math.max(0, Math.min(100, Number(cap) || 0));
  return (
    <div className="grid max-w-lg gap-5">
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          run("model", async () => {
            try {
              const changes: Record<string, unknown> = { model_provider: provider, model: provider === "disabled" || auto ? "" : model.trim() };
              if (auto) changes.openrouter = { ...savedCaps, max_usd_per_day: freeOnly ? 0 : dollars };
              await saveSettings(changes);
              await refreshSetup();
              toast.success("Research model saved");
            } catch (error) {
              toast.error("Model not saved", explain(error));
            }
          });
        }}
      >
        <Field label="Provider" hint={chosen.hint}>
          <Select value={provider} onValueChange={setProvider}>
            <SelectTrigger aria-label="Provider">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PROVIDERS.map((item) => (
                <SelectItem key={item.id} value={item.id}>
                  {item.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {auto && (
          <div className="grid gap-3 rounded-lg border p-4">
            <p className="text-sm text-muted-foreground">
              No model names to pick. Each morning the desk reads OpenRouter's model list and chooses: free models that return strict JSON for the
              specialists, and the best paid model within your price caps for the judge. Models that answer badly or call it wrong lose their place.
              Choosing costs no tokens.
            </p>
            <label className="flex items-center gap-3 text-sm">
              <Switch checked={freeOnly} onCheckedChange={setFreeOnly} /> Free models only (never spend money)
            </label>
            {!freeOnly && (
              <Field label="Most to spend per day (USD)" htmlFor="or-cap" hint="Paid models stop for the day at this amount. A typical day costs a few cents.">
                <Input id="or-cap" inputMode="decimal" className="num w-32" value={cap} onChange={(event) => setCap(event.target.value.replace(/[^\d.]/g, ""))} />
              </Field>
            )}
          </div>
        )}
        {provider !== "disabled" && !auto && (
          <Field label="Model name" htmlFor="model" hint="The exact identifier from the provider, e.g. gemini-2.5-flash.">
            <Input id="model" value={model} onChange={(event) => setModel(event.target.value)} className="font-mono" required />
          </Field>
        )}
        <Button type="submit" className="w-fit" disabled={busy !== null || !status?.config_exists}>
          {busy && <Loader2 className="animate-spin" />} Save model
        </Button>
      </form>
      {chosen.key && <SecretField name={chosen.key} label={auto ? "OpenRouter key" : `${chosen.label} key`} />}
      {auto && <OpenRouterCheck />}
      {!auto && <RoutingEditor />}
    </div>
  );
}

interface KeyStatus {
  is_free_tier?: boolean | null;
  free_requests_today: { used?: number | null; limit?: number | null; remaining?: number | null };
  usage_today_usd?: number | null;
  models: { free: number; paid_within_caps: number } | null;
}

/** What OpenRouter reports for the saved key. The key itself never comes back. */
function OpenRouterCheck() {
  const { setup: status } = useData();
  const [result, setResult] = useState<KeyStatus | null>(null);
  const { busy, run } = useBusy();
  const free = result?.free_requests_today;
  return (
    <div className="grid gap-2">
      <Button
        variant="outline"
        className="w-fit"
        disabled={busy !== null || !status?.secrets?.OPENROUTER_API_KEY?.set}
        onClick={() =>
          run("check", async () => {
            try {
              setResult(await setup<KeyStatus>("check_openrouter"));
            } catch (error) {
              toast.error("Key check failed", explain(error));
            }
          })
        }
      >
        {busy === "check" ? <Loader2 className="animate-spin" /> : <ShieldCheck />} Check key
      </Button>
      {result && (
        <dl className="num grid grid-cols-2 gap-x-4 gap-y-1 rounded-md bg-muted/50 px-3 py-2 text-sm">
          <dt className="text-muted-foreground">Free requests left today</dt>
          <dd>{free?.remaining != null ? `${free.remaining} of ${free.limit}` : "not reported"}</dd>
          <dt className="text-muted-foreground">Spent today</dt>
          <dd>${(result.usage_today_usd ?? 0).toFixed(3)}</dd>
          <dt className="text-muted-foreground">Models the desk can use</dt>
          <dd>{result.models ? `${result.models.free} free · ${result.models.paid_within_caps} paid within caps` : "list unavailable"}</dd>
        </dl>
      )}
      <p className="text-xs text-muted-foreground">
        OpenRouter's free models allow 20 requests a minute, and 50 a day until you have bought 10 credits, then 1,000 a day. A desk day uses
        about 30–60.
      </p>
    </div>
  );
}

function StocksStep() {
  const { setup: status, refreshSetup } = useData();
  const universe = status?.universe;
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<{ symbol: string; name: string }[]>([]);
  const [picked, setPicked] = useState<string[]>(universe?.symbols ?? []);
  const { busy, run } = useBusy();
  const file = useRef<HTMLInputElement>(null);
  const uploaded = status?.equity_list?.uploaded;

  useEffect(() => {
    if (!uploaded) return;
    const timer = window.setTimeout(async () => {
      try {
        setMatches((await setup<{ matches: { symbol: string; name: string }[] }>("search_symbols", { query })).matches);
      } catch {
        setMatches([]);
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [query, uploaded]);

  return (
    <div className="grid gap-6">
      <div className="grid gap-2">
        <p className="text-sm font-medium">1. NSE stock list</p>
        <p className="text-sm text-muted-foreground">
          Download <code className="font-mono text-foreground">EQUITY_L.csv</code> from nseindia.com → Market data → Securities available for trading,
          then choose it here. It stays on this machine.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <input
            ref={file}
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            id="equity"
            onChange={(event) => {
              const chosen = event.target.files?.[0];
              event.target.value = "";
              if (!chosen) return;
              run("upload", async () => {
                try {
                  if (chosen.size > 2_900_000) throw new Error("That file is too large to be EQUITY_L.csv");
                  const result = await setup<{ eq_symbols: number }>("upload_equity_list", { csv_text: await chosen.text() });
                  await refreshSetup();
                  toast.success("Stock list loaded", `${result.eq_symbols.toLocaleString("en-IN")} EQ-series stocks.`);
                } catch (error) {
                  toast.error("Stock list not loaded", error instanceof Error && !("status" in error) ? error.message : explain(error));
                }
              });
            }}
          />
          <Button variant="outline" disabled={busy !== null} onClick={() => file.current?.click()}>
            {busy === "upload" ? <Loader2 className="animate-spin" /> : <FileUp />}
            {uploaded ? "Replace EQUITY_L.csv" : "Choose EQUITY_L.csv"}
          </Button>
          {uploaded && <span className="text-xs text-muted-foreground">Loaded {dateTime(status?.equity_list?.uploaded_at)}</span>}
        </div>
      </div>

      <div className={cn("grid gap-3", !uploaded && "pointer-events-none opacity-50")} aria-disabled={!uploaded}>
        <p className="text-sm font-medium">2. Pick one to ten stocks</p>
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search by symbol or company" className="pl-9" aria-label="Search stocks" />
        </div>
        <div className="flex min-h-9 flex-wrap gap-2" aria-live="polite">
          {picked.map((symbol) => (
            <Badge key={symbol} variant="solid" className="gap-1 py-1 pl-3 pr-1.5 text-sm">
              {symbol}
              <button className="rounded-full p-0.5 hover:bg-white/20" onClick={() => setPicked(picked.filter((item) => item !== symbol))} aria-label={`Remove ${symbol}`}>
                <X className="size-3.5" />
              </button>
            </Badge>
          ))}
          {!picked.length && <span className="text-sm text-muted-foreground">None chosen yet.</span>}
        </div>
        {matches.length > 0 && (
          <ul className="max-h-60 max-w-md divide-y overflow-auto rounded-lg border">
            {matches.map((match) => {
              const chosen = picked.includes(match.symbol);
              return (
                <li key={match.symbol}>
                  <button
                    className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-accent disabled:opacity-50"
                    disabled={!chosen && picked.length >= 10}
                    onClick={() => setPicked(chosen ? picked.filter((item) => item !== match.symbol) : [...picked, match.symbol])}
                  >
                    <span className="w-24 font-medium">{match.symbol}</span>
                    <span className="flex-1 truncate text-muted-foreground">{match.name}</span>
                    {chosen && <Check className="size-4 text-primary" />}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="grid gap-2">
        <p className="text-sm font-medium">3. Match them to Kite instruments</p>
        <p className="text-sm text-muted-foreground">Needs today's Kite login. Lot sizes and tick sizes come from Kite's instrument list.</p>
        <Button
          className="w-fit"
          disabled={!picked.length || busy !== null || !status?.kite?.token?.today}
          onClick={() =>
            run("build", async () => {
              try {
                await setup("build_universe", { symbols: picked });
                await refreshSetup();
                toast.success("Stocks saved", picked.join(", "));
              } catch (error) {
                toast.error("Stocks not saved", explain(error));
              }
            })
          }
        >
          {busy === "build" && <Loader2 className="animate-spin" />} Save {picked.length || ""} stock{picked.length === 1 ? "" : "s"}
        </Button>
        {universe?.exists && (
          <p className="text-xs text-muted-foreground">
            Current list: {universe.symbols.join(", ") || "empty"} · built {universe.age_days ?? "?"} day(s) ago
          </p>
        )}
      </div>
    </div>
  );
}

function HistoryStep() {
  const { setup: status } = useData();
  const symbols = Object.entries(status?.history?.symbols ?? {});
  return (
    <div className="grid gap-4">
      <p className="text-sm text-muted-foreground">
        Downloads up to 180 days of 1-minute bars from Kite for your stocks. The strategies need at least 50 complete sessions each before they
        can be tested. On Oracle, this also runs every evening at 16:10.
      </p>
      {symbols.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-3">
          {symbols.map(([symbol, item]) => (
            <div key={symbol} className="rounded-lg border p-3">
              <p className="text-sm font-medium">{symbol.replace("NSE:", "")}</p>
              <p className="num text-xs text-muted-foreground">{item.sessions} of 50 sessions</p>
              <Progress value={Math.min(100, (item.sessions / 50) * 100)} className="mt-2" />
            </div>
          ))}
        </div>
      )}
      <JobRunner kind="history" label="Load 180 days of history" disabled={!status?.kite?.token?.today ? "Needs today's Kite login." : !status?.universe?.symbols?.length ? "Choose your stocks first." : false} />
    </div>
  );
}

function TournamentStep() {
  const { setup: status } = useData();
  const tournament = status?.tournament;
  return (
    <div className="grid gap-4">
      <p className="text-sm text-muted-foreground">
        Replays each strategy on your history with pessimistic fills and double costs. A strategy may trade only with at least 30 trades, a profit
        factor of 1.15 or better, profit in two of three periods and a non-negative latest period. If none pass, the desk sits out, which is the
        honest result.
      </p>
      {tournament?.ran && (
        <p className="text-sm">
          Last run {dateTime(tournament.as_of)}:{" "}
          {tournament.eligible.length ? <span className="text-success">{tournament.eligible.join(", ")} proven</span> : <span className="text-muted-foreground">nothing proven yet</span>}
        </p>
      )}
      <JobRunner kind="tournament" label="Run the strategy tournament" disabled={!status?.history?.exists ? "Load history first (step 8)." : false} />
    </div>
  );
}

function BookStep() {
  const { setup: status, refreshSetup, refreshState } = useData();
  const [values, setValues] = useState({ cash_inr: "200000", risk_inr: "500", daily_loss_inr: "1500", position_limit_inr: "30000" });
  const { busy, run } = useBusy();
  if (status?.book) return <Done>Your paper book exists. It is never overwritten; its journal is sealed with a checksum.</Done>;
  const fields: [keyof typeof values, string, string][] = [
    ["cash_inr", "Virtual cash", "Pretend money; no real funds move."],
    ["risk_inr", "Risk per trade", "Loss if a stop is hit, before costs."],
    ["daily_loss_inr", "Daily loss limit", "The desk stops for the day after this."],
    ["position_limit_inr", "Largest position", "Most rupees in one stock."],
  ];
  return (
    <form
      className="grid max-w-lg gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        run("book", async () => {
          try {
            await setup("create_book", values);
            await Promise.all([refreshSetup(), refreshState()]);
            toast.success("Paper book created", `${rupees(values.cash_inr)} of virtual cash.`);
          } catch (error) {
            toast.error("Book not created", explain(error));
          }
        });
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {fields.map(([key, label, hint]) => (
          <Field key={key} label={label} htmlFor={key} hint={hint}>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">₹</span>
              <Input id={key} inputMode="decimal" className="num pl-7" value={values[key]} onChange={(event) => setValues({ ...values, [key]: event.target.value.replace(/[^0-9.]/g, "") })} />
            </div>
          </Field>
        ))}
      </div>
      <Button type="submit" className="w-fit" disabled={busy !== null || !status?.universe?.symbols?.length}>
        {busy && <Loader2 className="animate-spin" />} Create paper book
      </Button>
    </form>
  );
}

function AttestStep() {
  const { setup: status, refreshSetup } = useData();
  const symbols = status?.universe?.symbols ?? [];
  const done = status?.attested_today ?? {};
  const [sources, setSources] = useState<Record<string, { s: string; e: string }>>({});
  const { busy, run } = useBusy();
  if (!symbols.length) return <p className="text-sm text-muted-foreground">Choose your stocks first.</p>;
  return (
    <div className="grid gap-4">
      <p className="text-sm text-muted-foreground">
        Each trading day, before the desk may plan a trade, you confirm two things yourself: the stock is not on an NSE surveillance list (ASM,
        GSM, ESM) and it has no results, board meeting or corporate action today. Note where you checked.
      </p>
      {symbols.map((symbol) => {
        const value = sources[symbol] ?? { s: "", e: "" };
        const set = (next: Partial<{ s: string; e: string }>) => setSources({ ...sources, [symbol]: { ...value, ...next } });
        return (
          <div key={symbol} className="rounded-lg border p-4">
            <div className="mb-3 flex items-center gap-2">
              <p className="font-medium">{symbol.replace("NSE:", "")}</p>
              {done[symbol] ? <Badge variant="success">Checked {dateTime(done[symbol].attested_at)}</Badge> : <Badge variant="outline">Not checked today</Badge>}
            </div>
            {!done[symbol] && (
              <form
                className="grid gap-3"
                onSubmit={(event) => {
                  event.preventDefault();
                  run(symbol, async () => {
                    try {
                      await setup("attest", { symbol, surveillance_source: value.s, event_source: value.e });
                      await refreshSetup();
                      toast.success(`${symbol.replace("NSE:", "")} checked for today`);
                    } catch (error) {
                      toast.error("Check not recorded", explain(error));
                    }
                  });
                }}
              >
                <Field label="Not under surveillance. Where did you check?" htmlFor={`s-${symbol}`}>
                  <Input id={`s-${symbol}`} value={value.s} onChange={(event) => set({ s: event.target.value })} placeholder="e.g. NSE ASM/GSM lists, 08:35" required />
                </Field>
                <Field label="No material event today. Where did you check?" htmlFor={`e-${symbol}`}>
                  <Input id={`e-${symbol}`} value={value.e} onChange={(event) => set({ e: event.target.value })} placeholder="e.g. NSE corporate announcements, 08:36" required />
                </Field>
                <Button type="submit" size="sm" className="w-fit" disabled={busy !== null}>
                  {busy === symbol && <Loader2 className="animate-spin" />} I checked both
                </Button>
              </form>
            )}
          </div>
        );
      })}
    </div>
  );
}

const PANELS: Record<string, () => JSX.Element> = {
  project: ProjectStep,
  profile: ProfileStep,
  kite_keys: KiteKeysStep,
  kite_login: KiteLoginStep,
  email: EmailStep,
  model: ModelStep,
  stocks: StocksStep,
  history: HistoryStep,
  tournament: TournamentStep,
  book: BookStep,
  attest: AttestStep,
};

export function SetupPage() {
  const { setup: status } = useData();
  const [, query] = useRoute();
  const steps = status?.steps ?? [];
  const firstOpen = steps.find((step) => !step.done)?.id ?? "project";
  const [current, setCurrent] = useState<string | null>(query.get("step"));
  const selected = current && PANELS[current] ? current : firstOpen;
  const done = steps.filter((step) => step.done).length;
  const complete = steps.length > 0 && done === steps.length;
  const [burst, setBurst] = useState(0);
  const wasComplete = useRef<boolean | null>(null);

  useEffect(() => {
    if (wasComplete.current === false && complete) setBurst((value) => value + 1);
    if (steps.length) wasComplete.current = complete;
  }, [complete, steps.length]);

  const Panel = PANELS[selected];
  const step = steps.find((item) => item.id === selected);
  const index = steps.findIndex((item) => item.id === selected);
  const mood: Mood = complete ? "happy" : step?.done ? "happy" : "thinking";

  return (
    <div className="grid gap-6">
      <section className="relative flex flex-col gap-4 rounded-xl border bg-card p-5 sm:flex-row sm:items-center">
        <div className="relative shrink-0 self-center">
          <Mascot kind={complete ? "pilot" : "blueprint"} size={88} mood={complete ? "wave" : "idle"} entrance="pop" />
          <Confetti fire={burst} />
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-semibold tracking-tight">{complete ? "Everything is set up" : "Set up your desk"}</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {complete
              ? "The desk can run each morning. Only today's Kite login and checks need you again tomorrow."
              : "Every step runs on your server. Keys go into a private file that only your user can read; this page never sees them again."}
          </p>
          <div className="mt-3 flex items-center gap-3">
            <Progress value={steps.length ? (done / steps.length) * 100 : 0} className="max-w-xs" />
            <span className="num text-sm text-muted-foreground">
              {done}/{steps.length || 11}
            </span>
          </div>
        </div>
        <Badge variant="outline" className="gap-1.5 self-start">
          <Lock className="size-3" /> Paper only
        </Badge>
      </section>

      <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
        <nav aria-label="Setup steps" className="min-w-0 lg:sticky lg:top-20 lg:self-start">
          <ol className="flex gap-2 overflow-x-auto pb-2 lg:grid lg:gap-1 lg:overflow-visible lg:pb-0">
            {steps.map((item, position) => (
              <li key={item.id} className="shrink-0">
                <button
                  onClick={() => {
                    setCurrent(item.id);
                    window.history.replaceState(null, "", `#/setup?step=${item.id}`);
                  }}
                  aria-current={item.id === selected ? "step" : undefined}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors",
                    item.id === selected ? "bg-primary/10 font-medium text-primary" : "hover:bg-accent",
                  )}
                >
                  <span
                    className={cn(
                      "grid size-6 shrink-0 place-items-center rounded-full border text-xs",
                      item.done ? "border-success bg-success text-white" : item.id === selected ? "border-primary text-primary" : "text-muted-foreground",
                    )}
                  >
                    {item.done ? <Check className="size-3.5" /> : position + 1}
                  </span>
                  <span className="whitespace-nowrap lg:whitespace-normal">{item.label}</span>
                </button>
              </li>
            ))}
          </ol>
        </nav>

        <Card className="min-w-0 self-start">
          <CardHeader className="flex-row items-start gap-4 space-y-0">
            <Mascot key={selected} kind={GUIDE[selected] ?? "pilot"} size={56} mood={mood} entrance="pop" />
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                Step {index + 1} of {steps.length || 11}
              </p>
              <CardTitle className="mt-1">{step?.label ?? "Setup"}</CardTitle>
              <CardDescription className="mt-1">{step?.detail}</CardDescription>
            </div>
            {step?.done && (
              <Badge variant="success" className="gap-1">
                <ShieldCheck className="size-3" /> Done
              </Badge>
            )}
          </CardHeader>
          <CardContent>
            {!status ? <p className="text-sm text-muted-foreground">Loading…</p> : selected !== "project" && !status.config_exists ? <p className="text-sm text-muted-foreground">Create the project first (step 1).</p> : <Panel />}
            {index >= 0 && index < steps.length - 1 && (
              <div className="mt-6 flex justify-end border-t pt-4">
                <Button variant="ghost" onClick={() => setCurrent(steps[index + 1].id)}>
                  Next: {steps[index + 1].label}
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
