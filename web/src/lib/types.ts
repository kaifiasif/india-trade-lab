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
    scan?: {
      stage: string;
      scanned: number;
      passed: number;
      dropped_by: Record<string, number>;
      dropped_at_open: string[];
      events_screened: boolean;
      notes: string[];
    } | null;
    ranked?: {
      symbol: string;
      score: number | null;
      eligible: boolean;
      watch: boolean;
      buildup: string | null;
      delivery_pct: number | null;
      gap_pct: number | null;
      rs_pct: number | null;
      events: { date: string; purpose: string }[];
    }[];
    confirmation?: Record<string, { confirmed: boolean; rvol: number | null; above_vwap: boolean; rs_since_open_pct: number | null; reasons: string[] }> | null;
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

export interface TrackRecord {
  graded: number;
  right: number;
  wrong: number;
  missed: number;
  accuracy: number;
}

export interface StockNote {
  symbol: string;
  sessions_studied?: number;
  avg_range_pct?: number;
  avg_abs_gap_pct?: number;
  up_close_share?: number;
  judge_picks_graded?: number;
  judge_picks_right?: number;
  paper_trades?: number;
  paper_wins?: number;
  avg_r?: number | null;
  cooldown_until?: string;
  cooldown_reason?: string;
}

export interface TierUsage {
  tier: string;
  provider: string;
  model: string;
  requests: number;
  requests_per_day: number;
  tokens: number;
  tokens_per_day: number;
  outcomes: Record<string, number>;
}

export interface LearningSummary {
  sessions_graded: number;
  totals: Record<string, number>;
  track_records: Record<string, TrackRecord>;
  lessons: { scope: string; subject: string; session: string; kind: string; text: string }[];
  stock_notes: StockNote[];
  finetune: { role: string; examples: number; graded: number; accuracy: number | null; advice: string }[];
  routing: { enabled: boolean; usage: TierUsage[] };
}
