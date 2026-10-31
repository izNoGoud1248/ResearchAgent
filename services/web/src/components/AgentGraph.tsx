import { type AgentNode, agentNodes, type RunProgress } from "../runProgress";

const labels: Record<AgentNode, string> = {
  clarify: "Clarifier",
  planner: "Planner",
  researcher: "Researchers",
  factCheck: "Fact-Checker",
  writer: "Writer",
  critic: "Critic",
  sensitivity: "Sensitivity",
  approval: "Approval",
  saveNote: "Save note",
};

const subtitles: Partial<Record<AgentNode, string>> = {
  researcher: "PARALLEL · MCP",
  factCheck: "A2A",
  saveNote: "MCP",
};

const boxWidth = 108;
const gap = 22;
const top = 30;
const boxHeight = 60;

/** The graph's shape never changes, so it is laid out by hand: one row, plus the writer-critic loop. */
export function AgentGraph({ progress }: { progress: RunProgress }) {
  const x = (index: number) => 8 + index * (boxWidth + gap);
  const writerX = x(agentNodes.indexOf("writer"));
  const criticX = x(agentNodes.indexOf("critic"));
  const width = x(agentNodes.length - 1) + boxWidth + 8;
  const middle = top + boxHeight / 2;

  // An edge "flows" while work is moving along it: the step before is done and the next one is active.
  const flowing = (from: AgentNode, to: AgentNode) => {
    const next = progress.stateOf(to);
    return progress.stateOf(from) === "done" && (next === "running" || next === "paused");
  };
  const loopActive = progress.timesRun("critic") > 0 && progress.stateOf("writer") === "running";

  return (
    <svg className="agentGraph" viewBox={`0 0 ${width} 136`} role="img" aria-label="Agent graph progress">
      <defs>
        <linearGradient id="edgeGradient" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0%" stopColor="#8b6cff" />
          <stop offset="100%" stopColor="#22d3ee" />
        </linearGradient>
        <filter id="nodeGlow" x="-30%" y="-40%" width="160%" height="180%">
          <feGaussianBlur stdDeviation="5" result="blur" />
          <feMerge>
            <feMergeNode in="blur" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
        <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
          <path d="M0,0 L10,5 L0,10 z" className="arrowHead" />
        </marker>
      </defs>

      {agentNodes.slice(0, -1).map((node, index) => {
        const next = agentNodes[index + 1];
        const active = next !== undefined && flowing(node, next);
        return (
          <line
            key={`edge-${node}`}
            x1={x(index) + boxWidth}
            y1={middle}
            x2={x(index + 1) - 2}
            y2={middle}
            className={active ? "edge flowing" : "edge"}
            markerEnd="url(#arrow)"
          />
        );
      })}
      <path
        d={`M ${criticX + boxWidth / 2} ${top + boxHeight} C ${criticX + boxWidth / 2} ${top + boxHeight + 36}, ${
          writerX + boxWidth / 2
        } ${top + boxHeight + 36}, ${writerX + boxWidth / 2} ${top + boxHeight + 2}`}
        className={loopActive ? "edge loop flowing" : "edge loop"}
        markerEnd="url(#arrow)"
      />
      <text x={(writerX + criticX + boxWidth) / 2} y={top + boxHeight + 44} className="loopLabel">
        revise
      </text>

      {agentNodes.map((node, index) => {
        const state = progress.stateOf(node);
        const runs = progress.timesRun(node);
        const lanes = node === "researcher" ? progress.researcherLanes() : [];
        const detail =
          lanes.length > 1
            ? `${lanes.filter((lane) => lane.state === "done").length}/${lanes.length} DONE`
            : state === "paused"
              ? "WAITING FOR YOU"
              : runs > 1
                ? `RUN x${runs}`
                : (subtitles[node] ?? state.toUpperCase());
        return (
          <g key={node} className={`agentNode ${state}`} transform={`translate(${x(index)}, ${top})`}>
            {/* Parallel researchers show as a stack of cards, one behind the other. */}
            {lanes.slice(1, 3).map((lane, offset) => (
              <rect key={lane.part} className="stackCard" x={(2 - offset) * 4} y={(offset - 2) * 4} width={boxWidth} height={boxHeight} rx="12" />
            ))}
            <rect width={boxWidth} height={boxHeight} rx="12" />
            <circle className="nodeDot" cx="12" cy="12" r="3" />
            <text x={boxWidth / 2} y="29" className="nodeLabel">
              {labels[node]}
            </text>
            <text x={boxWidth / 2} y="46" className="nodeDetail">
              {detail}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
