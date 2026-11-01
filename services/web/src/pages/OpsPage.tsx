import { useEffect, useState } from "react";
import type { ApiClient } from "../api/apiClient";
import type { Metrics, OpsStatus } from "../api/types";
import { StackedDays } from "../components/MetricsCharts";
import { Formatter } from "../formatter";

// Status colours are fixed in both themes; each series also shows its label and total, never colour alone.
export const statusColors = { good: "#0ca30c", warning: "#fab219", critical: "#d03b3b", neutral: "#8a93a8" };

const breakerLabels: Record<string, string> = {
  openai: "OpenAI",
  "tool:mcpSearch": "arXiv search tool",
  "tool:mcpNotes": "Notes tool",
  "tool:mcpLibrary": "Paper library tool",
};

export function OpsPage({ client }: { client: ApiClient }) {
  const [status, setStatus] = useState<OpsStatus | null>(null);
  const [error, setError] = useState("");
  const [metrics, setMetrics] = useState<Metrics | null>(null);

  // Trends change slowly: once a minute is plenty, unlike the live tiles.
  useEffect(() => {
    const load = () => void client.metrics().then(setMetrics).catch(() => setMetrics(null));
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, [client]);

  useEffect(() => {
    let stopped = false;
    const poll = () => {
      client
        .opsStatus()
        .then((next) => {
          if (!stopped) {
            setStatus(next);
            setError("");
          }
        })
        .catch(() => !stopped && setError("Could not load status."));
    };
    poll();
    const timer = setInterval(poll, 3000);
    return () => {
      stopped = true;
      clearInterval(timer);
    };
  }, [client]);

  if (!status) return <p className="muted">{error || "Loading..."}</p>;
  const waiting = status.queue.high + status.queue.normal + status.queue.low;

  return (
    <section>
      <span className="eyebrow">System health</span>
      <h1>Operations</h1>
      <p className="muted">Refreshes every 3 seconds.{error && ` ${error}`}</p>
      <div className="tiles">
        <div className="card tile">
          <span className="tileLabel">Live workers</span>
          <span className="tileValue">{status.workers}</span>
          <span className="muted">heartbeat in the last 30s</span>
        </div>
        <div className="card tile">
          <span className="tileLabel">Jobs waiting</span>
          <span className="tileValue">{waiting}</span>
          <span className="muted">
            high {status.queue.high} · normal {status.queue.normal} · low {status.queue.low}
          </span>
        </div>
        <div className="card tile">
          <span className="tileLabel">Jobs in progress</span>
          <span className="tileValue">{status.queue.leased}</span>
          <span className="muted">leased by workers</span>
        </div>
        {Object.entries(status.caches).map(([name, cache]) => (
          <div className="card tile" key={name}>
            <span className="tileLabel">{name === "llm" ? "LLM cache" : "arXiv cache"} hit rate</span>
            <span className="tileValue">{Formatter.percent(cache.hitRate)}</span>
            <span className="muted">
              {cache.hits} hits · {cache.misses} misses
            </span>
          </div>
        ))}
      </div>

      <h2>Circuit breakers</h2>
      <div className="tiles">
        {Object.entries(status.breakers).map(([name, state]) => (
          <div className="card tile" key={name}>
            <span className="tileLabel">{breakerLabels[name] ?? name}</span>
            <span className={`breaker breaker-${state}`}>{state === "halfOpen" ? "half open" : state}</span>
          </div>
        ))}
      </div>

      {metrics && <OpsTrends metrics={metrics} />}

      <h2>Traces and logs</h2>
      <p className="muted">Each run page links straight to its own trace. These open the tools themselves.</p>
      <div className="traceLinks">
        <a href={status.links.jaeger} target="_blank" rel="noreferrer noopener">
          Jaeger
        </a>
        <a href={`${status.links.kibana}/app/discover`} target="_blank" rel="noreferrer noopener">
          Kibana logs
        </a>
        <a href={Formatter.kibanaDashboard(status.links.kibana, "researchdesk-operations")} target="_blank" rel="noreferrer noopener">
          Operations dashboard
        </a>
        <a href={Formatter.kibanaDashboard(status.links.kibana, "researchdesk-security")} target="_blank" rel="noreferrer noopener">
          Security dashboard
        </a>
        {status.links.langfuse ? (
          <a href={status.links.langfuse} target="_blank" rel="noreferrer noopener">
            Langfuse
          </a>
        ) : (
          <span className="muted">Langfuse not configured</span>
        )}
      </div>
    </section>
  );
}

function OpsTrends({ metrics }: { metrics: Metrics }) {
  const days = metrics.runs.perDay;
  const total = (key: "completed" | "rejected" | "failed" | "open") => days.reduce((sum, day) => sum + day[key], 0);
  const runs = total("completed") + total("rejected") + total("failed") + total("open");
  const finished = total("completed") + total("rejected") + total("failed");
  const usd = days.reduce((sum, day) => sum + day.usd, 0);

  return (
    <>
      <h2>Last {metrics.days} days</h2>
      <div className="tiles">
        <div className="card tile">
          <span className="tileLabel">Runs</span>
          <span className="tileValue">{runs}</span>
          <span className="muted">{finished > 0 ? `${Formatter.percent(total("completed") / finished)} of finished runs completed` : "none finished"}</span>
        </div>
        <div className="card tile">
          <span className="tileLabel">Model spend</span>
          <span className="tileValue">{Formatter.usd(usd)}</span>
          <span className="muted">{runs > 0 ? `${Formatter.usd(usd / runs)} per run on average` : "no runs"}</span>
        </div>
        <div className="card tile">
          <span className="tileLabel">Median run time</span>
          <span className="tileValue">{metrics.runs.medianSeconds === null ? "-" : `${Math.round(metrics.runs.medianSeconds)} s`}</span>
          <span className="muted">completed runs, question to report</span>
        </div>
      </div>
      <div className="chartGrid">
        <div className="card">
          <h3 className="chartTitle">Runs per day</h3>
          <StackedDays
            rows={days}
            series={[
              { key: "completed", label: "Completed", color: statusColors.good },
              { key: "rejected", label: "Rejected", color: statusColors.warning },
              { key: "failed", label: "Failed", color: statusColors.critical },
              { key: "open", label: "Not finished", color: statusColors.neutral },
            ]}
          />
        </div>
        <div className="card">
          <h3 className="chartTitle">Model spend per day</h3>
          <StackedDays rows={days} series={[{ key: "usd", label: "Spend", color: "var(--chartSeries)" }]} format={Formatter.usd} />
        </div>
      </div>
      <div className="card tableCard">
        <h3 className="chartTitle">Tool calls through the gateway</h3>
        <table>
          <thead>
            <tr>
              <th>Tool</th>
              <th className="number">Calls</th>
              <th className="number">Median</th>
              <th className="number">95th percentile</th>
              <th className="number">Failed</th>
            </tr>
          </thead>
          <tbody>
            {metrics.gateway.tools.map((tool) => (
              <tr key={tool.tool}>
                <td className="mono">{tool.tool}</td>
                <td className="number">{tool.calls}</td>
                <td className="number">{Formatter.milliseconds(tool.p50)}</td>
                <td className="number">{Formatter.milliseconds(tool.p95)}</td>
                <td className="number">{tool.failed > 0 ? `${tool.failed} (${Formatter.percent(tool.failed / tool.calls)})` : "0"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
