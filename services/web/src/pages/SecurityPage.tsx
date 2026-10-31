import { useEffect, useState } from "react";
import type { ApiClient } from "../api/apiClient";
import type { AuditOutcome, AuditRow } from "../api/types";
import { Formatter } from "../formatter";
import { HashRouter } from "../routing";

const filters: { value: AuditOutcome | undefined; label: string }[] = [
  { value: undefined, label: "All" },
  { value: "denied", label: "Denied" },
  { value: "failed", label: "Failed" },
  { value: "allowed", label: "Allowed" },
];

export function SecurityPage({ client }: { client: ApiClient }) {
  const [outcome, setOutcome] = useState<AuditOutcome | undefined>("denied");
  const [rows, setRows] = useState<AuditRow[] | null>(null);

  useEffect(() => {
    setRows(null);
    client.audit(outcome).then(setRows).catch(() => setRows([]));
  }, [client, outcome]);

  return (
    <section>
      <span className="eyebrow">Gateway audit</span>
      <h1>Security</h1>
      <p className="muted">
        Every tool call through the MCP gateway: who called, what was decided and why, and how much PII was redacted.
      </p>
      <div className="segmented" role="tablist">
        {filters.map((filter) => (
          <button
            key={filter.label}
            role="tab"
            aria-selected={outcome === filter.value}
            className={outcome === filter.value ? "segment active" : "segment"}
            onClick={() => setOutcome(filter.value)}
          >
            {filter.label}
          </button>
        ))}
      </div>
      {!rows && <p className="muted">Loading...</p>}
      {rows?.length === 0 && <p className="muted">No matching tool calls.</p>}
      {rows && rows.length > 0 && (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Agent</th>
                <th>Tool</th>
                <th>Outcome</th>
                <th>Reason</th>
                <th>PII redacted</th>
                <th className="number">ms</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{Formatter.time(row.at)}</td>
                  <td>
                    {row.agent || "unknown"}
                    {row.issuer && row.issuer !== "orchestrator" && <span className="muted"> ({row.issuer})</span>}
                  </td>
                  <td>{row.tool}</td>
                  <td>
                    <span className={`badge outcome-${row.outcome}`}>{row.outcome}</span>
                  </td>
                  <td className="reason">
                    {row.reason || "-"}
                    {row.run && (
                      <>
                        {" "}
                        <a href={HashRouter.href({ page: "run", runId: row.run })}>run</a>
                      </>
                    )}
                  </td>
                  <td>
                    {Object.entries(row.pii)
                      .map(([kind, count]) => `${kind} x${count}`)
                      .join(", ") || "-"}
                  </td>
                  <td className="number">{row.ms}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <h2>Compliance report</h2>
      <p className="muted">The compliance report built from the audit log arrives in Stage 7.</p>
    </section>
  );
}
