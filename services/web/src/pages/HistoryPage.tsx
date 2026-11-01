import { useEffect, useState } from "react";
import type { ApiClient } from "../api/apiClient";
import type { RunSummary } from "../api/types";
import { StatusBadge } from "../components/StatusBadge";
import { Formatter } from "../formatter";
import { HashRouter } from "../routing";

export function HistoryPage({ client }: { client: ApiClient }) {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);

  useEffect(() => {
    client.listRuns().then(setRuns).catch(() => setRuns([]));
  }, [client]);

  if (!runs) return <p className="muted">Loading...</p>;

  return (
    <section>
      <span className="eyebrow">All runs</span>
      <h1>History</h1>
      {runs.length === 0 && <p className="muted">No runs yet.</p>}
      {runs.length > 0 && (
        <div className="tableWrap">
          <table className="historyTable">
            <thead>
              <tr>
                <th>Question</th>
                <th>Status</th>
                <th>Started</th>
                <th>Duration</th>
                <th className="number optionalColumn">Tokens</th>
                <th className="number optionalColumn">Cost</th>
                <th className="optionalColumn">Models</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>
                    <a href={HashRouter.href({ page: "run", runId: run.id })}>{run.question}</a>
                  </td>
                  <td>
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="nowrap" title={Formatter.time(run.created)}>
                    {Formatter.shortTime(run.created)}
                  </td>
                  <td className="nowrap">{Formatter.duration(run.created, run.updated)}</td>
                  <td className="number optionalColumn">{Formatter.tokens(run.cost)}</td>
                  <td className="number optionalColumn">{Formatter.cost(run.cost)}</td>
                  <td className="muted nowrap optionalColumn" title={Formatter.models(run.cost)}>
                    {Formatter.modelSummary(run.cost)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
