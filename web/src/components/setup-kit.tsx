import { useEffect, useRef, useState } from "react";
import { CircleCheck, Eye, EyeOff, KeyRound, Loader2, Play, Trash2 } from "lucide-react";
import { ApiError, get, setup } from "@/lib/api";
import { useData } from "@/lib/context";
import { toast } from "@/lib/toast";
import type { Job } from "@/lib/types";
import { cn, dateTime } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export function explain(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "The dashboard server did not answer. Is it still running?";
}

/** A write-only secret: the value is sent once and never shown again, only "saved, ends 1234". */
export function SecretField({ name, label, hint, placeholder }: { name: string; label: string; hint?: React.ReactNode; placeholder?: string }) {
  const { setup: status, refreshSetup } = useData();
  const info = status?.secrets?.[name];
  const [value, setValue] = useState("");
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const id = `secret-${name}`;

  async function save(next: string) {
    setBusy(true);
    try {
      await setup("save_secret", { key: name, value: next });
      setValue("");
      await refreshSetup();
      toast.success(next ? `${label} saved` : `${label} removed`, next ? "Stored on this machine only, readable by your user alone." : undefined);
    } catch (error) {
      toast.error(`Could not save ${label.toLowerCase()}`, explain(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-1.5">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor={id} className="text-sm font-medium">
          {label}
        </label>
        {info?.set ? (
          <Badge variant="success">
            <KeyRound className="size-3" /> Saved · ends {info.last4}
          </Badge>
        ) : (
          <Badge variant="outline">Not set</Badge>
        )}
      </div>
      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (value.trim()) save(value.trim());
        }}
      >
        <div className="relative flex-1">
          <Input
            id={id}
            type={show ? "text" : "password"}
            autoComplete="off"
            spellCheck={false}
            value={value}
            placeholder={info?.set ? "Enter a new value to replace it" : placeholder}
            onChange={(event) => setValue(event.target.value)}
            className="pr-10 font-mono"
          />
          <button
            type="button"
            className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-muted-foreground hover:text-foreground"
            onClick={() => setShow((value) => !value)}
            aria-label={show ? "Hide what you typed" : "Show what you typed"}
          >
            {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        </div>
        <Button type="submit" disabled={busy || !value.trim()}>
          {busy ? <Loader2 className="animate-spin" /> : null}
          Save
        </Button>
        {info?.set && (
          <Button type="button" variant="ghost" size="icon" disabled={busy} onClick={() => save("")} aria-label={`Remove ${label}`}>
            <Trash2 />
          </Button>
        )}
      </form>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

const STATE_BADGE: Record<string, { label: string; variant: "default" | "success" | "warning" | "destructive" | "outline" }> = {
  running: { label: "Running", variant: "default" },
  succeeded: { label: "Done", variant: "success" },
  failed: { label: "Failed", variant: "destructive" },
  timed_out: { label: "Timed out", variant: "destructive" },
  interrupted: { label: "Interrupted", variant: "warning" },
};

/** Start a fixed server job and follow its log as it runs. */
export function JobRunner({ kind, label, description, disabled, onDone }: { kind: string; label: string; description?: string; disabled?: string | false; onDone?: (job: Job) => void }) {
  const { setup: status, refreshSetup, refreshState } = useData();
  const latest = status?.jobs?.find((job) => job.kind === kind) ?? null;
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [log, setLog] = useState("");
  const [open, setOpen] = useState(false);
  const offset = useRef(0);
  const pre = useRef<HTMLPreElement>(null);
  const active = jobId ?? (latest?.state === "running" ? latest.id : null);

  useEffect(() => {
    if (!active) return;
    let stop = false;
    offset.current = 0;
    setLog("");
    setOpen(true);
    async function tick() {
      try {
        const next = await get<Job & { offset: number; text: string }>(`/api/setup/jobs/${active}?offset=${offset.current}`);
        if (stop) return;
        offset.current = next.offset;
        if (next.text) setLog((value) => (value + next.text).slice(-40_000));
        setJob(next);
        if (next.state === "running") {
          window.setTimeout(tick, 1000);
        } else {
          setJobId(null);
          await Promise.all([refreshSetup(), refreshState()]);
          if (next.state === "succeeded") toast.success(`${label}: done`);
          else toast.error(`${label}: ${STATE_BADGE[next.state]?.label.toLowerCase() ?? next.state}`, "Open the log below to see why.");
          onDone?.(next);
        }
      } catch {
        if (!stop) window.setTimeout(tick, 3000);
      }
    }
    tick();
    return () => {
      stop = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  useEffect(() => {
    if (pre.current) pre.current.scrollTop = pre.current.scrollHeight;
  }, [log]);

  async function start() {
    try {
      const started = await setup<Job & { reused: boolean }>("run_job", { kind });
      setJobId(started.id);
      if (started.reused) toast.info(`${label} is already running`, "Following the running job.");
    } catch (error) {
      toast.error(`Could not start ${label.toLowerCase()}`, explain(error));
    }
  }

  const shown = job ?? latest;
  const running = shown?.state === "running" || Boolean(jobId);
  const badge = shown ? STATE_BADGE[shown.state] : null;
  return (
    <div className="rounded-lg border">
      <div className="flex flex-wrap items-center gap-3 p-4">
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{label}</p>
          <p className="text-xs text-muted-foreground">
            {disabled || description || "Runs on the server; you can leave this page."}
            {shown && !running && ` · last run ${dateTime(shown.finished_at ?? shown.started_at)}`}
          </p>
        </div>
        {badge && <Badge variant={badge.variant}>{running ? <Loader2 className="size-3 animate-spin" /> : shown?.state === "succeeded" ? <CircleCheck className="size-3" /> : null}{badge.label}</Badge>}
        {shown && (
          <Button
            variant="ghost"
            size="sm"
            aria-expanded={open}
            onClick={async () => {
              if (!open && !active && shown) {
                try {
                  setLog((await get<{ text: string }>(`/api/setup/jobs/${shown.id}`)).text);
                } catch {
                  setLog("");
                }
              }
              setOpen((value) => !value);
            }}
          >
            {open ? "Hide log" : "Log"}
          </Button>
        )}
        <Button size="sm" variant={running ? "outline" : "default"} disabled={running || Boolean(disabled)} onClick={start}>
          {running ? <Loader2 className="animate-spin" /> : <Play />}
          {running ? "Running" : shown ? "Run again" : "Run"}
        </Button>
      </div>
      {open && (
        <pre
          ref={pre}
          aria-live="polite"
          className={cn("max-h-64 overflow-auto border-t bg-muted/50 p-4 font-mono text-xs leading-relaxed text-muted-foreground", !log && "italic")}
        >
          {log || (running ? "Waiting for output…" : "This run wrote nothing.")}
        </pre>
      )}
    </div>
  );
}
