import { useState } from "react";
import { ArrowRight, Loader2, Zap } from "lucide-react";
import { get, setup } from "@/lib/api";
import { useData } from "@/lib/context";
import { toast } from "@/lib/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Field } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SecretField, explain } from "@/components/setup-kit";

interface Tier {
  name: string;
  provider: string;
  model: string;
  requests_per_day?: number;
  requests_per_minute?: number;
  tokens_per_day?: number;
  reset_timezone?: string;
}
interface Routing {
  enabled: boolean;
  tiers: Tier[];
  simple: string[];
  complex: string[];
  escalate: boolean;
  cache: boolean;
  store_prompts: boolean;
  max_escalations_per_day: number;
}

const PROVIDERS = [
  { id: "gemini", label: "Google Gemini", key: "GEMINI_API_KEY", reset: "America/Los_Angeles" },
  { id: "local", label: "Local model (Ollama)", key: "LOCAL_LLM_API_KEY", reset: "UTC" },
  { id: "anthropic", label: "Anthropic Claude", key: "ANTHROPIC_API_KEY", reset: "UTC" },
  { id: "openai", label: "OpenAI", key: "OPENAI_API_KEY", reset: "UTC" },
];

const number = (value: string) => Math.max(0, Math.min(1_000_000, Number(value.replace(/\D/g, "")) || 0));

function TierFields({ tier, onChange, title, note }: { tier: Tier; onChange: (next: Tier) => void; title: string; note: string }) {
  const id = `tier-${tier.name}`;
  return (
    <fieldset className="grid gap-3 rounded-lg border p-4">
      <legend className="px-1 text-sm font-medium">{title}</legend>
      <p className="-mt-1 text-xs text-muted-foreground">{note}</p>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Provider">
          <Select
            value={tier.provider}
            onValueChange={(provider) => onChange({ ...tier, provider, reset_timezone: PROVIDERS.find((item) => item.id === provider)?.reset ?? "UTC" })}
          >
            <SelectTrigger aria-label={`${title} provider`}>
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
        <Field label="Model ID" htmlFor={`${id}-model`}>
          <Input id={`${id}-model`} className="font-mono" value={tier.model} onChange={(event) => onChange({ ...tier, model: event.target.value.trim() })} placeholder={tier.provider === "local" ? "qwen2.5:7b" : "exact ID from the provider"} />
        </Field>
        <Field label="Requests per day" htmlFor={`${id}-rpd`} hint="0 means no cap.">
          <Input id={`${id}-rpd`} inputMode="numeric" className="num" value={String(tier.requests_per_day ?? 0)} onChange={(event) => onChange({ ...tier, requests_per_day: number(event.target.value) })} />
        </Field>
        <Field label="Requests per minute" htmlFor={`${id}-rpm`} hint="0 means no cap.">
          <Input id={`${id}-rpm`} inputMode="numeric" className="num" value={String(tier.requests_per_minute ?? 0)} onChange={(event) => onChange({ ...tier, requests_per_minute: number(event.target.value) })} />
        </Field>
      </div>
    </fieldset>
  );
}

/** Simple jobs to the free tier, hard ones to the strong tier, each falling back to the other. */
export function RoutingEditor() {
  const { setup: status, refreshSetup } = useData();
  const saved = (status?.settings?.routing ?? {}) as Partial<Routing>;
  const find = (name: string) => saved.tiers?.find((tier) => tier.name === name);
  const [enabled, setEnabled] = useState(Boolean(saved.enabled));
  const [free, setFree] = useState<Tier>(find("free") ?? { name: "free", provider: "gemini", model: "", requests_per_day: 200, requests_per_minute: 10, reset_timezone: "America/Los_Angeles" });
  const [useStrong, setUseStrong] = useState(Boolean(find("strong")));
  const [strong, setStrong] = useState<Tier>(find("strong") ?? { name: "strong", provider: "anthropic", model: "", requests_per_day: 30, requests_per_minute: 0, reset_timezone: "UTC" });
  const [escalations, setEscalations] = useState(String(saved.max_escalations_per_day ?? 10));
  const [busy, setBusy] = useState(false);
  const keys = [...new Set([free, ...(useStrong ? [strong] : [])].map((tier) => PROVIDERS.find((item) => item.id === tier.provider)!))];

  async function save() {
    setBusy(true);
    try {
      const tiers = [free, ...(useStrong ? [strong] : [])];
      const routing: Routing = {
        enabled,
        tiers,
        simple: useStrong ? ["free", "strong"] : ["free"],
        complex: useStrong ? ["strong", "free"] : ["free"],
        escalate: true,
        cache: true,
        store_prompts: true,
        max_escalations_per_day: Math.min(100, number(escalations)),
      };
      const view = await get<{ version: string }>("/api/setup/settings");
      await setup("save_settings", { version: view.version, changes: { routing } });
      await refreshSetup();
      toast.success(enabled ? "Smart routing is on" : "Routing saved (off)", enabled ? "Simple jobs now go to your free tier first." : undefined);
    } catch (error) {
      toast.error("Routing not saved", explain(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="grid gap-4 border-t pt-5" aria-labelledby="routing-title">
      <div className="flex items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary">
          <Zap className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <h3 id="routing-title" className="font-semibold">
            Smart routing <Badge variant="outline" className="ml-1 align-middle">saves tokens</Badge>
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            The six specialists, the two sub-agents and the debaters do simple, short jobs, so they go to your free tier. The judge goes to the
            strong tier. A tier that hits its limit, refuses or answers badly hands over to the next one, and a rerun on the same day is answered
            from a cache at no cost. When this is on it replaces the single model above.
          </p>
        </div>
        <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Turn smart routing on" />
      </div>
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge>Simple jobs</Badge> free <ArrowRight className="size-3" /> {useStrong ? "strong" : "rules only"}
        <span className="mx-2 text-border">|</span>
        <Badge>Judge</Badge> {useStrong ? "strong" : "free"} <ArrowRight className="size-3" /> {useStrong ? "free" : "rules only"}
      </div>
      <TierFields
        tier={free}
        onChange={setFree}
        title="Free tier"
        note="Enter the limits Google AI Studio (or your provider) shows for your key; they change, so check them. A local model on your server has no limits but is slower."
      />
      <label className="flex items-center gap-3 text-sm">
        <Switch checked={useStrong} onCheckedChange={setUseStrong} /> Add a strong tier for the judge (optional, may cost money)
      </label>
      {useStrong && <TierFields tier={strong} onChange={setStrong} title="Strong tier" note="Set a daily cap so a busy day can never run up a bill." />}
      <Field label="Most escalations per day" htmlFor="escalations" hint="Each one is an extra call when a cheaper tier fails.">
        <Input id="escalations" inputMode="numeric" className="num w-32" value={escalations} onChange={(event) => setEscalations(event.target.value.replace(/\D/g, ""))} />
      </Field>
      <div className="grid gap-4">
        {keys.map((item) => (
          <SecretField key={item.key} name={item.key} label={`${item.label} key`} hint={item.id === "local" ? "Only if your local server asks for one." : undefined} />
        ))}
      </div>
      <Button className="w-fit" onClick={save} disabled={busy || !status?.config_exists || (enabled && (!free.model || (useStrong && !strong.model)))}>
        {busy && <Loader2 className="animate-spin" />} Save routing
      </Button>
    </section>
  );
}
