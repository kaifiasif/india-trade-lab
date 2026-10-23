// Shape of the observatory export (`observatory.py --export-preview`), reduced to what
// the recap draws. Every number shown in the video comes from these recorded fields.
export type Call = {
  side: "buy" | "sell" | string;
  at: string;
  qty?: number;
  fill_inr?: string | null;
  stop?: string | null;
  target?: string | null;
  reason?: string;
  status?: string;
  symbol?: string;
};

export type Agent = { id: string; name: string; count: number; status: string };

export type RecapProps = {
  run_id?: string | null;
  mode?: string;
  source?: string;
  scenario?: string;
  halt_reason?: string | null;
  metrics?: Record<string, string | number | null | undefined>;
  limits?: Record<string, string>;
  prices?: { at: string; price: string }[];
  calls?: Call[];
  agents?: Agent[];
};

export const money = (value: unknown, digits = 2) =>
  value == null || !Number.isFinite(Number(value))
    ? "—"
    : new Intl.NumberFormat("en-IN", {
        style: "currency",
        currency: "INR",
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      }).format(Number(value));

export const clockIST = (iso: string) =>
  new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));

export const dateIST = (iso: string) =>
  new Intl.DateTimeFormat("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(iso));

// Minutes since midnight IST, so the session axis is 09:15–15:30 wherever it renders.
export const minutesIST = (iso: string) => {
  const date = new Date(iso);
  return (
    ((date.getUTCHours() * 60 + date.getUTCMinutes() + 330) % 1440) +
    date.getUTCSeconds() / 60
  );
};
export const OPEN = 9 * 60 + 15;
export const CLOSE = 15 * 60 + 30;

export const symbolOf = (props: RecapProps) =>
  props.calls?.find((call) => call.symbol)?.symbol ??
  (props.source?.includes("NSE") ? "NSE" : "Paper session");

export const isSynthetic = (props: RecapProps) =>
  props.mode === "synthetic_replay" ||
  (props.source ?? "").toUpperCase().includes("SYNTHETIC");
