import { useEffect, useState } from "react";
import type { ApiClient } from "../api/apiClient";
import type { OpsStatus } from "../api/types";
import { Formatter } from "../formatter";

const breakerLabels: Record<string, string> = {
  openai: "OpenAI",
  "tool:mcpSearch": "arXiv search tool",
  "tool:mcpNotes": "Notes tool",
};

export function OpsPage({ client }: { client: ApiClient }) {
  const [status, setStatus] = useState<OpsStatus | null>(null);
  const [error, setError] = useState("");

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

      <h2>Traces and logs</h2>
      <p className="muted">Each run page links straight to its own trace. These open the tools themselves.</p>
      <div className="traceLinks">
        <a href={status.links.jaeger} target="_blank" rel="noreferrer noopener">
          Jaeger
        </a>
        <a href={`${status.links.kibana}/app/discover`} target="_blank" rel="noreferrer noopener">
          Kibana
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
