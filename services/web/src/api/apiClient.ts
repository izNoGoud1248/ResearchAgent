import type {
  AuditOutcome,
  AuditRow,
  FollowUpAnswer,
  OpsStatus,
  ReviewAction,
  Role,
  Run,
  RunStatus,
  RunSummary,
} from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly retryAfter: number | null,
  ) {
    super(detail);
  }
}

/** Talks to the API with the browser's session cookie (httpOnly, set by signIn), so no key is held in JavaScript. */
export class ApiClient {
  static readonly base = "/api";

  url(path: string): string {
    return ApiClient.base + path;
  }

  async role(): Promise<Role> {
    return (await this.request<{ role: Role }>("/me")).role;
  }

  async signIn(apiKey: string): Promise<Role> {
    return (await this.request<{ role: Role }>("/session", { method: "POST", body: JSON.stringify({ apiKey }) })).role;
  }

  async signOut(): Promise<void> {
    await fetch(this.url("/session"), { method: "DELETE", credentials: "same-origin" });
  }

  ask(question: string, sensitive: boolean): Promise<{ runId: string }> {
    return this.request("/runs", { method: "POST", body: JSON.stringify({ question, sensitive }) });
  }

  listRuns(status?: RunStatus): Promise<RunSummary[]> {
    return this.request(status ? `/runs?status=${status}` : "/runs");
  }

  getRun(runId: string): Promise<Run> {
    return this.request(`/runs/${encodeURIComponent(runId)}`);
  }

  decide(runId: string, action: ReviewAction, note: string): Promise<{ status: string }> {
    return this.request(`/runs/${encodeURIComponent(runId)}/decision`, {
      method: "POST",
      body: JSON.stringify({ action, note }),
    });
  }

  askFollowUp(runId: string, question: string): Promise<FollowUpAnswer> {
    return this.request(`/runs/${encodeURIComponent(runId)}/ask`, { method: "POST", body: JSON.stringify({ question }) });
  }

  opsStatus(): Promise<OpsStatus> {
    return this.request("/ops/status");
  }

  audit(outcome?: AuditOutcome): Promise<AuditRow[]> {
    return this.request(outcome ? `/audit?outcome=${outcome}` : "/audit");
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const response = await fetch(this.url(path), {
      ...init,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    });
    if (!response.ok) {
      const retryAfter = response.headers.get("Retry-After");
      throw new ApiError(response.status, await this.errorDetail(response), retryAfter ? Number(retryAfter) : null);
    }
    // The API is ours and typed on the server; this is the one place its JSON is trusted to match.
    return (await response.json()) as T;
  }

  private async errorDetail(response: Response): Promise<string> {
    try {
      const body: unknown = await response.json();
      if (typeof body === "object" && body !== null && "detail" in body && typeof body.detail === "string") {
        return body.detail;
      }
    } catch {
      // Not JSON; fall back to the status text below.
    }
    return response.statusText || `request failed with ${response.status}`;
  }
}
