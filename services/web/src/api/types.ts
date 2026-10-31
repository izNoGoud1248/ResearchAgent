export type Role = "user" | "approver";

export type RunStatus = "queued" | "running" | "awaitingClarification" | "awaitingApproval" | "resuming" | "completed" | "rejected" | "failed";

export interface CostTotal {
  inputTokens?: number;
  outputTokens?: number;
  usd?: number;
  [modelCalls: `calls:${string}`]: number;
}

export interface RunSummary {
  id: string;
  question: string;
  sensitive: boolean;
  status: RunStatus;
  created: string;
  updated: string;
  note: string;
  cost: CostTotal;
  error: string;
  revisions: number;
}

export type ReviewAction = "approve" | "revise" | "reject";

export interface FollowUpSource {
  paperId: string;
  title: string;
  section: string;
  excerpt: string;
  matchedBy: string[];
}

export interface FollowUpAnswer {
  answer: string;
  sources: FollowUpSource[];
  papersWithFullText: number;
  ungroundedCitations?: string[];
}

export interface ClarifyingQuestion {
  question?: string;
  options?: string[];
}

export interface Run extends RunSummary {
  report: string;
  clarification: ClarifyingQuestion;
  review: string;
  traceId: string;
  revisionsLeft: number;
}

export interface ToolLinks {
  jaeger: string;
  kibana: string;
  langfuse: string;
}

export interface RunEvent {
  id: string;
  kind: string;
  data: Record<string, unknown>;
}

export type BreakerState = "closed" | "open" | "halfOpen";

export interface CacheStats {
  hits: number;
  misses: number;
  hitRate: number;
}

export interface OpsStatus {
  workers: number;
  queue: { high: number; normal: number; low: number; leased: number };
  breakers: Record<string, BreakerState>;
  caches: Record<string, CacheStats>;
  links: ToolLinks;
}

export type AuditOutcome = "allowed" | "denied" | "failed";

export interface AuditRow {
  id: number;
  at: string;
  tool: string;
  outcome: AuditOutcome;
  ms: number;
  reason: string;
  agent: string;
  issuer: string;
  run: string;
  trace: string;
  pii: Record<string, number>;
}
