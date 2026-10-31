# ResearchDesk Plan

A small but real multi-agent system for practising every production topic from the notebooks. Real OpenAI, real arXiv, real Redis and Postgres, real MCP and A2A SDKs, real traces and logs.

## 1. What it does

A user asks a research question, for example "What are the latest approaches to prompt injection defense?"

1. A Planner splits the question into sub-questions.
2. Several Researchers run in parallel. Each searches arXiv through an MCP tool and summarizes.
3. A Fact-Checker (a separate service reached over A2A) verifies the claims.
4. A Writer merges everything into a report.
5. A Critic scores the report. If it is weak, the Writer revises (max 2 loops).
6. If the report is sensitive, a human must approve before it is returned.
7. The Writer can save the final report through an MCP notes tool.

## 2. Standards

1. Keep it simple.
2. Comments only when necessary.
3. Short README, no emojis anywhere.
4. Handle exceptions only where something real can fail (network, LLM, untrusted input).
5. Always `uv run`, never `python3`, never bare `pip`.
6. TypeScript: strict mode, never `any`.
7. Everything class based. No loose functions except tiny entry points.
8. camelCase names, no underscores: files `inputGuard.py`, classes `InputGuard`, methods `checkMessage`, folders `mcpSearch`. Names fixed by outside tools stay as they are. React component files use PascalCase (`LiveRun.tsx`).
9. Real services only. Tests run against real Redis. No mocks of our own code.
10. Secrets only through `.env` (git-ignored). Never printed, never committed.

## 3. Architecture

```
Web UI (React, TypeScript, nginx)
  |  same origin, nginx proxies /api
  v
API (FastAPI)  --  input guard, auth, rate limit, cache
  |  pushes jobs                    ^ reads live events
  v                                 |
Redis JobQueue  -->  Orchestrator workers (LangGraph)  --> Redis Streams (run events)
  Planner -> [Researcher x N] -> Fact-Checker -> Writer <-> Critic -> Approval -> Answer
                  | MCP                | A2A          | MCP
                  v                    v              v
            MCP Gateway  ---->  mcpSearch   Fact-Checker   mcpNotes
            (token check, RBAC,  (arXiv)    (Agent Card)
             PII, HMAC + content
             checks, audit)     mcpEvil (security tests only)

Redis: queue, cache, rate limits, breaker state, run event streams, worker heartbeats
Postgres: LangGraph checkpoints, notes, runs, audit
Supervisor: health checks, restarts in Compose, alerts in Kubernetes
Telemetry: OpenTelemetry -> Collector -> Jaeger, Langfuse, Filebeat -> Logstash -> Elasticsearch -> Kibana
```

## 4. Decisions

- **Python 3.12 and uv.**
- **Postgres** holds LangGraph checkpoints, notes, runs (status, duration, tokens, cost, model) and audit. The gateway writes each audit event to Postgres and also logs it so Kibana sees it.
- **Agent identity at the gateway.** The orchestrator signs a 5-minute Ed25519 JWT per tool call (`sub` = agent role, `runId`, `traceId`). The gateway holds only public keys, verifies, then looks the role up in its own policy file, which alone decides allowed tools and hours. The LLM never sees the token. The Fact-Checker has its own key pair and can only sign as itself. Known limit: a compromised orchestrator could sign as any of its agents.
- **Tool response signing.** Each tool server signs responses with its own HMAC key shared only with the gateway. The gateway checks the signature, then scans content for poisoning. `mcpEvil` is tested both unsigned and signed-but-poisoned.
- **Sensitive reports.** Sensitive if the user ticks the toggle or a cheap classifier flags it after the Critic.
- **Approval.** `POST /runs/{runId}/decision` with `{action, note}`, approver role only, where action is `approve`, `revise` or `reject`. Revise needs a note, sends it to the writer, reruns the critic and returns to approval, at most twice, without repeating the research. Reject ends the run with the draft kept and nothing saved. The inbox reads `GET /runs?status=awaitingApproval`.
- **API auth.** API keys with roles `user` and `approver`.
- **Workers from Stage 3.** The API queues jobs and the orchestrator worker runs them from the start, so later stages scale it rather than rebuild it.
- **Agent tokens carry an audience.** Tokens for the gateway (`mcpGateway`) cannot be replayed against the Fact-Checker (`factChecker`).
- **No separate API response cache.** Deterministic LLM calls are cached in the LLM layer and arXiv searches in the search server.
- **Live updates.** Workers write events to a Redis Stream per run. The API serves them as SSE with `Last-Event-ID` replay. The browser reads the stream with `fetch` so it can send the auth header.
- **Replica count.** Workers write a heartbeat key with a TTL; Ops counts live keys. Works in Compose and Kubernetes.
- **Queue.** One Redis list per priority so KEDA's Redis list scaler can watch depth. Leased jobs return to the queue if a worker dies.
- **Redis eviction.** `noeviction`, so queue and breaker keys are never dropped. The response cache enforces its own LRU cap.
- **Langfuse.** Langfuse Cloud free tier (self-hosted v3 is too heavy for this project). It receives the same OpenTelemetry spans from the collector, so no separate Langfuse SDK and the trace id matches Jaeger and Kibana.
- **Stage order.** Stage 6 was built before Stage 5: the observability stack runs in Compose while our services still run on the host.
- **Agent harness.** `libs/harness` runs a model in a tool-calling loop with budgets (steps, dollars, seconds), errors and refusals fed back to the model, repeat detection, context compaction and per-call hooks; tools are discovered from the MCP gateway. The agent researcher uses it and keeps only claims citing papers it retrieved. A/B on the six eval questions (cold cache): agent vs fixed workflow, citations 100% both, supported 0.954 vs 0.99, judge 4.83 vs 4.71, cost +7%, time +48%. No real quality gain, so the fixed workflow stays the default (`RESEARCHER_MODE`); autonomy should pay off once researchers have more than one real tool.
- **Containers (Stage 5).** One Python image for all services and an nginx image for the UI; Compose profile `app`. Browser sign-in uses a signed httpOnly session cookie instead of keeping the API key in JavaScript. MCP DNS-rebinding protection stays on, allowing each server's own hostname.
- **Fact-checking against cited papers.** The Fact-Checker fetches every paper a claim cites (`arxiv.fetch`, Fact-Checker only) and judges the claim against it; its own search is extra evidence. Judging only against a separate search measured search overlap, not truth (34 of 34 "supported" had the cited paper in that search, 14 of 14 "unsupported" did not). Up to 20 claims are checked per run, up from 8.
- **Kibana dashboards as code.** Two Lens dashboards (operations and cost, security and audit) built in Python and imported by `kibanaSetup`, plus a 30-day ILM retention policy. Kibana covers trends across runs; Jaeger covers one run; Langfuse covers LLM calls.
- **Trace across the queue.** The API stores the run's traceparent; start and resume jobs carry it, so one run is one trace even across a human approval.
- **Local ports.** Redis on 6380, Postgres on 5433, to avoid clashing with other projects.
- **ANP.** Last stage, decided after Kubernetes works. Reuses the agent signing keys.

## 5. Web UI

Vite, React, TypeScript (strict), plain CSS, served by nginx.

1. **Ask.** Question box, sensitive toggle. Blocked inputs show the guard's reason.
2. **Live run.** Fixed agent graph drawn in SVG with each node waiting, running or done. Streaming text, tool calls, A2A calls and critic loops as they happen.
3. **Approval inbox.** Pending reports with Approve and Reject.
4. **History.** Past runs with status, duration, tokens, cost and model.
5. **Ops.** Queue depth, rate limiter and breaker state per tool, cache hit rate, live workers, links to Jaeger, Langfuse and Kibana for the current trace ID (base URLs come from `/ops/status`).
6. **Security.** Audit feed and compliance report.

Endpoints: `GET /runs/{id}/events` (SSE), `GET /runs`, `POST /runs/{id}/decision`, `GET /ops/status`, `GET /audit`.

## 6. Topic map

| Topic | Class | Stage |
|---|---|---|
| Input validation, injection detection | `InputGuard` | 1 |
| Agent identity | `AgentTokenIssuer`, `AgentTokenVerifier` | 1 |
| Agent RBAC (scopes, time windows) | `PermissionGuard` | 1 |
| PII redaction | `PiiRedactor` | 1 |
| Tool response validation (HMAC, poisoning) | `ResponseSigner`, `ResponseValidator` | 1 |
| Rate limiting (token bucket) | `RateLimiter` | 1 |
| Circuit breaker | `CircuitBreaker` | 1 |
| Retry, backoff, timeout | `Retrier` | 1 |
| Priority queue, backpressure | `JobQueue` | 1 |
| Response cache (TTL, LRU) | `ResponseCache` | 1 |
| Model router | `ModelRouter` | 1 |
| Token and cost tracking | `CostTracker` | 1 |
| LLM client tying the above together | `LlmClient` | 1 |
| MCP servers and gateway | `SearchServer`, `NotesServer`, `McpGateway` | 2 |
| Human approval | `ApprovalGate` | 3 |
| Batching, parallelism | LangGraph `Send` fan-out with `max_concurrency` (no separate `BatchRunner` needed) | 3 |
| A2A | `FactCheckerAgent`, `A2aClient` | 3 |
| Tracing and logging | `Tracer`, `JsonLogger` | 6 |
| Supervisor and health checks | `Supervisor` | 7 |
| Compliance report | `ComplianceReporter` | 7 |
| ANP-style signing | `AgentIdentity` | 10 |

## 7. Build stages

1. **Core libs.** Settings, guardrails, reliability, LLM layer. Tested against real Redis and the real OpenAI API.
2. **Tools.** arXiv MCP server, notes MCP server, MCP Gateway with token check, RBAC, PII and validation.
3. **Agents.** LangGraph graph, FastAPI, Postgres checkpoints, approval gate, A2A Fact-Checker.
4. **Web UI.** Ask and Live run first, then Approval, History, Ops and Security.
5. **Containers.** Dockerfiles (including nginx) and Compose profiles `core`, `observability`, `elk`.
6. **Observability.** OpenTelemetry to Jaeger, Langfuse, JSON logs to ELK, one trace ID across all three.
7. **Resilience.** Workers on the job queue, supervisor, compliance report.
8. **Security tests.** Injection, poisoned tool, permission violations, PII leaks.
9. **Kubernetes.** kind, probes, graceful shutdown, ConfigMap and Secret, NetworkPolicy, KEDA on queue depth, replica cap tied to the OpenAI quota.
10. **Stretch.** ANP-style signed agent messages.

## 8. Testing

- Unit tests per class against real Redis: `uv run pytest -m "not llm"`.
- Tests that call OpenAI are marked `llm`: `uv run pytest -m llm -s`.
- Integration: one real question through the whole graph.
- Security: prompt injection, role escalation, poisoned tool output, PII in and out.
- Load: bursts proving backpressure, rate limiting, breaker opening and KEDA scaling.
- Playwright tests for the UI against the real backend.
