import type { ResearcherLane } from "../runProgress";

// The agent harness's stop reasons, in words.
const stopReasons: Record<string, string> = {
  finished: "finished",
  budgetSteps: "step budget reached",
  budgetUsd: "cost budget reached",
  budgetSeconds: "time budget reached",
  stuck: "stopped repeating itself",
  noFinish: "ended without a summary",
};

/** One row per parallel researcher, so the fan-out and each researcher's progress are visible. */
export function ResearcherPanel({ lanes }: { lanes: ResearcherLane[] }) {
  if (lanes.length === 0) return null;
  const done = lanes.filter((lane) => lane.state === "done").length;

  return (
    <div className="card researcherPanel">
      <div className="panelHeading">
        <h2>Parallel researchers</h2>
        <span className="muted">
          {lanes.length} in parallel · {done} done
        </span>
      </div>
      <ol>
        {lanes.map((lane) => (
          <li key={lane.part} className={`lane lane-${lane.state}`}>
            <span className="laneNumber">#{lane.part}</span>
            <span className="laneDot" aria-hidden="true" />
            <div className="laneBody">
              <span className="laneQuestion">{lane.question || "Waiting for its sub-question"}</span>
              <span className="laneDetail">{ResearcherPanelText.detail(lane)}</span>
            </div>
            <span className="laneState">{lane.state}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}

class ResearcherPanelText {
  static detail(lane: ResearcherLane): string {
    if (lane.state === "waiting") return "Not started";
    const calls = `${lane.toolCalls} tool call${lane.toolCalls === 1 ? "" : "s"}`;
    if (lane.state === "running") return lane.lastAction ? `${calls} · now: ${lane.lastAction}` : "Starting";
    const parts = [calls, `${lane.papers} paper${lane.papers === 1 ? "" : "s"} cited`];
    if (lane.steps > 0) parts.push(`${lane.steps} agent steps, ${stopReasons[lane.stopReason] ?? lane.stopReason}`);
    return parts.join(" · ");
  }
}
