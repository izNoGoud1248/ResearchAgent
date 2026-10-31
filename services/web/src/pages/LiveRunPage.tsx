import { useCallback, useEffect, useMemo, useState } from "react";
import type { ApiClient } from "../api/apiClient";
import { EventStream } from "../api/eventStream";
import type { Role, Run, RunEvent, ToolLinks } from "../api/types";
import { AgentGraph } from "../components/AgentGraph";
import { ClarifyForm } from "../components/ClarifyForm";
import { DecisionForm } from "../components/DecisionForm";
import { FollowUpBox } from "../components/FollowUpBox";
import { MarkdownView } from "../components/MarkdownView";
import { StatusBadge } from "../components/StatusBadge";
import { EventDescriber } from "../eventDescriber";
import { RunProgress } from "../runProgress";
import { Formatter } from "../formatter";
import { TraceLinks } from "../traceLinks";

interface LiveRunPageProps {
  client: ApiClient;
  runId: string;
  role: Role;
}

export function LiveRunPage({ client, runId, role }: LiveRunPageProps) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [loadError, setLoadError] = useState("");
  const [links, setLinks] = useState<ToolLinks | null>(null);
  const progress = useMemo(() => RunProgress.from(events), [events]);

  useEffect(() => {
    client
      .opsStatus()
      .then((status) => setLinks(status.links))
      .catch(() => setLinks(null));
  }, [client]);

  const refresh = useCallback(() => {
    client
      .getRun(runId)
      .then(setRun)
      .catch(() => setLoadError("This run could not be loaded."));
  }, [client, runId]);

  useEffect(() => {
    refresh();
    const controller = new AbortController();
    void new EventStream(client).follow(
      runId,
      (event) => {
        setEvents((previous) => (previous.some((seen) => seen.id === event.id) ? previous : [...previous, event]));
        if (event.kind === "runStarted" || event.kind === "awaitingApproval" || event.kind === "awaitingClarification" || EventStream.finalKinds.has(event.kind)) refresh();
      },
      controller.signal,
    );
    return () => controller.abort();
  }, [client, runId, refresh]);

  if (loadError) return <p className="errorText">{loadError}</p>;
  if (!run) return <p className="muted">Loading run...</p>;

  const showDecision = role === "approver" && run.status === "awaitingApproval";
  const report = progress.outcome || run.status === "awaitingApproval" ? run.report : "";

  return (
    <section className="liveRun">
      <div className="runHeader">
        <div>
          <span className="eyebrow">Live run</span>
          <h1>{run.question}</h1>
          <ul className="runMeta">
            <li>
              run <strong>{run.id.slice(0, 8)}</strong>
            </li>
            <li>{Formatter.time(run.created)}</li>
            <li>
              cost <strong>{Formatter.cost(run.cost)}</strong>
            </li>
            <li>
              tokens <strong>{Formatter.tokens(run.cost)}</strong>
            </li>
            {progress.criticScores.length > 0 && (
              <li>
                critic <strong>{progress.criticScores.join(" → ")}</strong>
              </li>
            )}
            {run.traceId && (
              <li>
                trace <strong>{run.traceId.slice(0, 12)}</strong>
              </li>
            )}
          </ul>
          {links && run.traceId && (
            <p className="traceLinks">
              {TraceLinks.forTrace(links, run.traceId).map((link) => (
                <a key={link.label} href={link.href} target="_blank" rel="noreferrer noopener">
                  {link.label}
                </a>
              ))}
            </p>
          )}
        </div>
        <StatusBadge status={run.status} />
      </div>

      <div className="card graphCard">
        <AgentGraph progress={progress} />
      </div>

      {run.status === "awaitingClarification" && run.clarification.question && (
        <div className="card approvalBanner">
          <strong>Before researching, the Clarifier needs one answer from you.</strong>
          <ClarifyForm client={client} runId={run.id} question={run.clarification} onAnswered={refresh} />
        </div>
      )}
      {run.status === "awaitingApproval" && (
        <div className="card approvalBanner">
          <strong>
            {run.revisions > 0
              ? `Revised draft ${run.revisions} is ready for review.`
              : "This report is held for human approval."}
          </strong>
          {showDecision ? (
            <DecisionForm client={client} runId={run.id} revisionsLeft={run.revisionsLeft} onDecided={refresh} />
          ) : (
            <span className="muted"> An approver needs to review it before it is saved.</span>
          )}
        </div>
      )}
      {run.status === "failed" && <div className="alert">{run.error}</div>}

      <div className="runColumns">
        <div className="card feed">
          <h2>Activity</h2>
          {events.length === 0 && <p className="muted">Waiting for a worker to pick this run up...</p>}
          <ol>
            {events.map((event) => (
              <li key={event.id} className={`feedItem kind-${event.kind}`}>
                <time>{Formatter.streamTime(event.id)}</time>
                <span>{EventDescriber.describe(event)}</span>
              </li>
            ))}
          </ol>
        </div>
        <div className="card">
          <h2>Report</h2>
          {report ? <MarkdownView markdown={report} /> : <p className="muted">The report appears here when the writer and critic are done.</p>}
          {(run.note || run.review) && (
            <div className="reportFooter muted">
              {run.note && (
                <div>
                  Saved as note <span className="mono">{run.note}</span>
                </div>
              )}
              {run.review && <div>Reviewer note: {run.review}</div>}
            </div>
          )}
          {report && run.status !== "failed" && <FollowUpBox client={client} runId={run.id} />}
        </div>
      </div>
    </section>
  );
}
