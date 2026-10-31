export type AgentState =
  | "idle"
  | "listening"
  | "thinking"
  | "executing"
  | "waiting_approval"
  | "collaborating"
  | "completed"
  | "failed";

export interface ToolInfo {
  id: string;
  category: string;
  description: string;
  risk: string;
  timeout_s: number;
  availability: "implemented" | "requires_credentials" | "simulated" | "unavailable";
  availability_detail: string;
  input_schema: Record<string, unknown>;
  agents?: string[];
}

export interface Agent {
  id: string;
  name: string;
  full_name: string;
  role: string;
  color: string;
  icon: string;
  personality: string[];
  communication_style: string;
  responsibilities: string[];
  boundaries: string[];
  workflow: string;
  permission_level: string;
  tools: string[];
  model: { tier: string; provider: string | null; model: string | null; preferred: string[]; temperature: number; max_output_tokens: number };
  limits: { max_steps: number; timeout_s: number; max_retries: number; max_tokens_per_task: number; cost_limit_usd_per_task: number };
  memory: { read_namespaces: string[]; write_namespaces: string[] };
  delegation: { can_delegate_to: string[]; review_focus: string };
  voice: { lang: string; pitch: number; rate: number; preferred_voices: string[]; muted?: boolean; description: string };
  canon_notes: string[];
  system_prompt: string;
  model_in_use: { provider: string | null; model: string | null; reason: string; fallbacks?: string[] };
  live: { status: AgentState; task_id: string | null; detail: string; updated_at: string };
  metrics: { tasks: Record<string, number>; tokens: number; cost_usd: number; success_rate: number | null; avg_seconds?: number };
  tool_details: ToolInfo[];
}

export interface Task {
  id: string;
  root_id: string;
  parent_id: string | null;
  conversation_id: string | null;
  agent_id: string;
  kind: string;
  requested_by: string;
  instruction: string;
  status: string;
  result: string | null;
  error: string | null;
  depth: number;
  agent_chain: string[];
  provider: string | null;
  model: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  steps: number;
  sources: { url: string; title?: string; retrieved_at?: string }[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface AgentMessage {
  id: string;
  correlation_id: string;
  task_id: string;
  root_id: string;
  sender: string;
  recipient: string;
  type: string;
  status: string;
  payload: Record<string, unknown>;
  evidence: unknown[];
  permission_context: Record<string, unknown>;
  created_at: string;
}

export interface Approval {
  id: string;
  task_id: string;
  agent_id: string;
  tool_id: string;
  action: string;
  target: string;
  expected_effects: string;
  risks: string;
  permissions: string[];
  tool_input: Record<string, unknown>;
  status: string;
  created_at: string;
  decided_at: string | null;
}

export interface Memory {
  id: string;
  namespace: string;
  layer: string;
  content: string;
  source: string;
  created_by: string;
  consent: boolean;
  tags: string[];
  created_at: string;
  updated_at: string;
  expires_at: string | null;
}

export interface AuditEntry {
  id: number;
  ts: string;
  actor: string;
  action: string;
  target: string;
  task_id: string | null;
  outcome: string;
  detail: Record<string, unknown>;
}

export interface Turn {
  id: number;
  conversation_id: string;
  role: "user" | "assistant";
  agent_id: string;
  content: string;
  task_id: string | null;
  created_at: string;
}

export interface SystemStatus {
  version: string;
  host: { os: string; release: string; arch: string; python: string };
  mode: string;
  emergency_stop: boolean;
  memory_enabled: boolean;
  providers: Record<string, { configured: boolean; healthy: boolean; detail: string; pool_size: number }>;
  active_providers: string[];
  tools: Record<string, string>;
  workspace_roots: string[];
  database: string;
  requests_today: number;
  quota: { limit: number; remaining: number; used: number } | null;
  running_tasks: number;
  pending_approvals: number;
}

export interface StarkEvent {
  type: string;
  ts: string;
  data: Record<string, any>;
}

export interface ModelHealth {
  ok: number;
  failed: number;
  last_error: string | null;
  last_latency_ms: number | null;
  cooling_down_s: number;
  cooldown_reason: string | null;
}

export interface CatalogModel {
  id: string;
  name: string;
  context_length: number | null;
  tools: boolean;
  chat: boolean;
  input_modalities: string[];
  excluded: boolean;
  in_pool: boolean;
  snapshot: { ok: boolean; ms?: number; error?: string; note?: string } | null;
  health: ModelHealth | null;
}

export interface ModelsInfo {
  configured: boolean;
  catalog_error: string | null;
  catalog: CatalogModel[];
  pool: string[];
  tiers: Record<string, string[]>;
  pins: Record<string, string>;
  quota: { limit: number; remaining: number; used: number } | null;
  requests_today: number;
}

export interface CheckIssue {
  level: "fail" | "warn";
  code: string;
  message: string;
}

export interface ContentItem {
  id: string;
  platform: string;
  kind: string;
  text: string;
  thread: string[];
  media: { description: string; alt_text: string }[];
  reply_to: string | null;
  campaign: string;
  sponsored: boolean;
  status: string;
  scheduled_for: string | null;
  paused: boolean;
  simulated: boolean;
  external_url: string | null;
  created_by: string;
  error: string | null;
  check: { verdict: "pass" | "warn" | "fail" | null; issues: CheckIssue[] };
  review: { verdict: string; notes: string; by: string } | null;
  due: boolean;
  fingerprint: string;
  auto_publish: boolean;
  autopilot?: AutopilotMeta | null;
  category?: string;
  reply_control?: string | null;
  evergreen_days?: number | null;
}

export interface GateReason {
  level: "reject" | "review";
  code: string;
  message: string;
}

export interface AutopilotMeta {
  campaign_id: string;
  research_id: string;
  source_url: string;
  source_title: string;
  source: string;
  story_score: number;
  keywords: string[];
  hashtags: string[];
  gate: { verdict: "pass" | "review" | "reject"; score: number; reasons: GateReason[] };
  fact_check: { supported: boolean; problems: string[] } | null;
  trust: TrustLevel;
  slot: string;
  approved_by?: string;
  veto_until?: string;
  needs_you?: string[];
  engagement?: Record<string, number>;
  engagement_score?: number;
}

export type TrustLevel = "copilot" | "veto" | "auto";

export interface CampaignSource {
  type: "rss" | "hn" | "reddit" | "search";
  value: string;
}

export interface RunReport {
  at: string;
  campaign: string;
  researched: number;
  new_stories: number;
  drafted: number;
  scheduled: number;
  awaiting: number;
  rejected: number;
  errors: string[];
  skipped?: string;
}

export interface Campaign {
  id: string;
  name: string;
  enabled: boolean;
  paused: boolean;
  pause_reason: string | null;
  topics: string[];
  keywords: string[];
  avoid_terms: string[];
  audience: string;
  tone: string;
  platforms: string[];
  sources: CampaignSource[];
  post_times: string[];
  timezone: string;
  daily_cap: number;
  min_gap_minutes: number;
  trust_level: TrustLevel;
  veto_minutes: number;
  link_policy: "always" | "never";
  fact_check: boolean;
  research_every_h: number;
  max_new_per_run: number;
  last_run_at: string | null;
  next_run_at: string | null;
  streak: number;
  auto_unlocked: boolean;
  auto_unlock_needs: number;
  history: RunReport[];
  counts: { awaiting: number; going_out: number; published_24h: number; rejected_24h: number };
}

export interface ResearchStory {
  id: string;
  source: string;
  title: string;
  url: string;
  summary: string;
  published_at: string | null;
  score: number;
  keywords: string[];
  status: "new" | "used" | "skipped";
  note: string | null;
  created_at: string;
}

export interface KeywordRow {
  keyword: string;
  hashtag: string | null;
  posts: number;
  measured: number;
  avg_engagement: number | null;
}

export interface CampaignDetail extends Campaign {
  keywords_table: KeywordRow[];
  research: ResearchStory[];
  items: ContentItem[];
}

export interface SocialAccount {
  platform: string;
  name: string;
  mode: "connected" | "simulation";
  char_limit: number;
  detail: string;
  can_connect: boolean;
  connected_as: string | null;
  source: "env" | "dashboard" | null;
}

export interface Engagement {
  likes: number;
  reposts: number;
  replies: number;
  quotes?: number;
}

export interface PublishedPost {
  id: string;
  platform: string;
  kind: string;
  text: string;
  url: string | null;
  campaign: string;
  simulated: boolean;
  published_at: string;
  engagement: Engagement | null;
  score: number | null;
  evergreen_days?: number | null;
}

export interface AnalyticsReport {
  counts: Record<string, Record<string, number>>;
  posts: PublishedPost[];
  totals: { likes: number; reposts: number; replies: number; quotes: number };
  measured: number;
  errors: string[];
  fetched_at: string;
}

export interface Watch {
  id: string;
  kind: "keyword" | "hashtag" | "account";
  query: string;
  platforms: string[];
  label: string;
  enabled: boolean;
  interval_min: number;
  last_run_at: string | null;
  last_error: string | null;
  created_at: string;
  new: number;
}

export interface Mention {
  id: string;
  watch_id: string;
  platform: string;
  external_id: string;
  url: string | null;
  author: string;
  text: string;
  posted_at: string | null;
  likes: number;
  reposts: number;
  replies: number;
  category: string;
  status: "new" | "done" | "dismissed";
  created_at: string;
}

export interface Competitor {
  watch_id: string;
  account: string;
  label: string;
  posts: number;
  avg_score: number;
  best: { text: string; url: string | null; likes: number; reposts: number; replies: number }[];
}

export interface Snippet {
  id: string;
  kind: "template" | "hashtags" | "signature";
  name: string;
  body: string;
  platforms: string[];
  created_at: string;
}

export interface PostingPlan {
  categories: { name: string; share: number; color: string }[];
  slots: { weekday: number; time: string }[];
}

export interface GrowthReport {
  series: Record<string, { day: string; followers: number; following: number; posts: number }[]>;
  summary: Record<string, { followers: number; change_total: number; change_7d: number; since: string }>;
  posted_days: Record<string, number>;
  streak: number;
  active_days_30: number;
}
