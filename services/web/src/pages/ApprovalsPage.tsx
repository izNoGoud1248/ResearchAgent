import { useCallback, useEffect, useState } from "react";
import type { ApiClient } from "../api/apiClient";
import type { ReviewAction, Role, Run, RunSummary } from "../api/types";
import { DecisionForm } from "../components/DecisionForm";
import { MarkdownView } from "../components/MarkdownView";
import { Formatter } from "../formatter";
import { HashRouter } from "../routing";

const decisionMessages: Record<ReviewAction, string> = {
  approve: "Approved. The worker is saving the report.",
  revise: "Changes requested. The writer is revising; the new draft will come back here.",
  reject: "Rejected. The report will not be saved.",
};

export function ApprovalsPage({ client, role }: { client: ApiClient; role: Role }) {
  const [pending, setPending] = useState<RunSummary[] | null>(null);
  const [open, setOpen] = useState<Run | null>(null);
  const [message, setMessage] = useState("");

  const load = useCallback(() => {
    client.listRuns("awaitingApproval").then(setPending).catch(() => setPending([]));
  }, [client]);

  useEffect(load, [load]);

  if (role !== "approver") return <p className="muted">Only approvers can see the approval inbox.</p>;
  if (!pending) return <p className="muted">Loading...</p>;

  const decided = (action: ReviewAction) => {
    setMessage(decisionMessages[action]);
    setOpen(null);
    load();
  };

  return (
    <section>
      <span className="eyebrow">Human in the loop</span>
      <h1>Approval inbox</h1>
      {message && <p className="notice">{message}</p>}
      {pending.length === 0 && <p className="muted">Nothing is waiting for approval.</p>}
      <div className="inbox">
        <ul className="runList">
          {pending.map((run) => (
            <li key={run.id}>
              <button className={open?.id === run.id ? "runRow selected" : "runRow"} onClick={() => void client.getRun(run.id).then(setOpen)}>
                <strong>{run.question}</strong>
                <span className="muted">
                  {Formatter.time(run.updated)}
                  {run.revisions > 0 && ` · revised draft ${run.revisions}`}
                </span>
              </button>
            </li>
          ))}
        </ul>
        {open && (
          <div className="card">
            <p className="muted">
              <a href={HashRouter.href({ page: "run", runId: open.id })}>Open the live run</a>
            </p>
            <MarkdownView markdown={open.report} />
            {open.review && open.revisions > 0 && <p className="muted">Your last request: {open.review}</p>}
            <DecisionForm client={client} runId={open.id} revisionsLeft={open.revisionsLeft} onDecided={decided} />
          </div>
        )}
      </div>
    </section>
  );
}
