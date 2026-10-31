import { useEffect, useState } from "react";
import type { ApiClient } from "../api/apiClient";
import type { AuditOutcome, AuditRow, Metrics } from "../api/types";
import { RankedBars, StackedDays } from "../components/MetricsCharts";
import { Formatter } from "../formatter";
import { HashRouter } from "../routing";
import { statusColors } from "./OpsPage";

const filters: { value: AuditOutcome | undefined; label: string }[] = [
  { value: undefined, label: "All" },
  { value: "denied", label: "Denied" },
  { value: "failed", label: "Failed" },
  { value: "allowed", label: "Allowed" },
];

export function SecurityPage({ client }: { client: ApiClient }) {
  const [outcome, setOutcome] = useState<AuditOutcome | undefined>("denied");
  const [rows, setRows] = useState<AuditRow[] | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);

  useEffect(() => {
    client.metrics().then(setMetrics).catch(() => setMetrics(null));
  }, [client]);

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
      {metrics && <GatewayTrends metrics={metrics} />}
      <h2>Audit log</h2>
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
    </section>
  );
}

function GatewayTrends({ metrics }: { metrics: Metrics }) {
  const days = metrics.gateway.perDay;
  const total = (key: "allowed" | "denied" | "failed") => days.reduce((sum, day) => sum + day[key], 0);
  const calls = total("allowed") + total("denied") + total("failed");

  return (
    <>
      <h2>Last {metrics.days} days</h2>
      <div className="tiles">
        <div className="card tile">
          <span className="tileLabel">Tool calls</span>
          <span className="tileValue">{calls}</span>
          <span className="muted">through the MCP gateway</span>
        </div>
        <div className="card tile">
          <span className="tileLabel">Denied</span>
          <span className="tileValue">{total("denied")}</span>
          <span className="muted">{calls > 0 ? `${Formatter.percent(total("denied") / calls)} of calls` : "no calls"}</span>
        </div>
        <div className="card tile">
          <span className="tileLabel">PII redacted</span>
          <span className="tileValue">{metrics.gateway.pii.redactions}</span>
          <span className="muted">items in {metrics.gateway.pii.calls} calls</span>
        </div>
      </div>
      <div className="chartGrid">
        <div className="card">
          <h3 className="chartTitle">Gateway decisions per day</h3>
          <StackedDays
            rows={days}
            series={[
              { key: "allowed", label: "Allowed", color: statusColors.good },
              { key: "denied", label: "Denied", color: statusColors.warning },
              { key: "failed", label: "Failed", color: statusColors.critical },
            ]}
          />
        </div>
        <div className="card">
          <h3 className="chartTitle">Top reasons for denial</h3>
          <RankedBars items={metrics.gateway.refusals.map((item) => ({ label: item.reason, value: item.count }))} color="var(--chartSeries)" />
        </div>
      </div>
      <p className="traceLinks">
        <a href={Formatter.kibanaDashboard(metrics.links.kibana, "researchdesk-security")} target="_blank" rel="noreferrer noopener">
          Security dashboard in Kibana
        </a>
      </p>
    </>
  );
}
