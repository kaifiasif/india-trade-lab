export interface Metrics {
  cash_inr?: string;
  realized_inr?: string;
  equity_inr?: string;
  initial_cash_inr?: string;
  open_positions?: number;
  fills?: number;
  quotes?: number;
  proposals?: number;
  blocked?: number;
}

export interface Call {
  id?: string;
  at?: string;
  kind?: string;
  symbol?: string;
  side?: string;
  qty?: number;
  stop?: string;
  target?: string;
  reason?: string;
  status?: string;
  detail?: string;
  fill_inr?: string;
  phase?: string;
}

export interface StageAgent {
  id: string;
  name: string;
  role: string;
  count: number;
  status: string;
  implementation?: string;
}

export interface DeskPick {
  symbol: string;
  rating: string;
  conviction: string;
  strategy?: string;
  reason: string;
  risk?: string | null;
}

export interface DeskState {
  report: {
    session_date: string;
    as_of: string;
    mode: string;
    reason: string;
    summary?: string;
    watching: string[];
    picks: DeskPick[];
    dropped: { symbol: string; why: string }[];
    specialists: Record<string, string>;
    strategies: string[];
    assessed: number;
    pool: number;
  } | null;
  scorecard: {
    as_of: string;
    sessions?: number;
    strategies: Record<string, { eligible: boolean; reason: string; doubled_costs: { trades?: number; net_inr?: number; profit_factor?: number } }>;
  } | null;
}

export interface DashboardState {
  run_id?: string | null;
  status: string;
  mode?: string;
  scenario?: string;
  clock?: string;
  phase?: string;
  halt_reason?: string | null;
  metrics?: Metrics;
  agents?: StageAgent[];
  calls?: Call[];
  events?: Record<string, unknown>[];
  positions?: Record<string, { qty: number; stop_inr?: string; target_inr?: string; entry_inr?: string }>;
  limits?: Record<string, string>;
  controls?: Record<string, number | string>;
  prices?: { at: string; price: string }[];
  watchlist?: { candidates: { rank: number; symbol: string; reason: string; history_sessions: number; last_session: string }[]; reason?: string; mode?: string };
  histories?: { symbol: string; completed_sessions: number; minimum_sessions: number; history_ready: boolean; decision: string; reason: string; last_session?: string | null }[];
  research?: {
    report: (Record<string, unknown> & { status?: string; calls?: Record<string, unknown>[]; memory?: Record<string, unknown>; goal?: Record<string, string>; as_of?: string; archived?: boolean }) | null;
    crypto: Record<string, unknown>[];
    service: Record<string, unknown> | null;
  };
  desk?: DeskState;
  error?: string | null;
}

export interface SecretInfo {
  key: string;
  set: boolean;
  last4: string | null;
  label: string;
}

export interface Job {
  id: string;
  kind: string;
  label: string;
  state: string;
  started_at: string;
  finished_at: string | null;
  exit_code: number | null;
}

export interface SetupStatus {
  profile: { name?: string };
  config_exists: boolean;
  settings: Record<string, unknown>;
  secrets: Record<string, SecretInfo>;
  kite: { api_key: boolean; api_secret: boolean; token: { set: boolean; saved_at: string | null; today: boolean } };
  email: { server: boolean; password: boolean; recipients: boolean };
  model: { provider: string; key_set: boolean };
  universe: { exists: boolean; as_of?: string; age_days?: number; symbols: string[]; names?: Record<string, string> };
  equity_list: { uploaded: boolean; uploaded_at: string | null };
  history: { exists: boolean; symbols: Record<string, { sessions: number; last: string | null }> };
  tournament: { ran: boolean; as_of?: string; eligible: string[] };
  attested_today: Record<string, { attested_at: string }>;
  book: boolean;
  jobs: Job[];
  job_kinds: Record<string, string>;
  steps: { id: string; label: string; done: boolean; detail: string }[];
}
