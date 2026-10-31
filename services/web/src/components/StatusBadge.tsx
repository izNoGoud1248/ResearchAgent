import type { RunStatus } from "../api/types";

const labels: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  awaitingClarification: "Needs your answer",
  awaitingApproval: "Needs approval",
  resuming: "Resuming",
  completed: "Completed",
  rejected: "Rejected",
  failed: "Failed",
};

export function StatusBadge({ status }: { status: RunStatus }) {
  return (
    <span className={`badge status-${status}`}>
      <span className="badgeDot" aria-hidden="true" />
      {labels[status]}
    </span>
  );
}
