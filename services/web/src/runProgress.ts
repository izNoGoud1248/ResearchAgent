import type { RunEvent } from "./api/types";

export const agentNodes = [
  "planner",
  "researcher",
  "factCheck",
  "writer",
  "critic",
  "sensitivity",
  "approval",
  "saveNote",
] as const;

export type AgentNode = (typeof agentNodes)[number];
export type NodeState = "waiting" | "running" | "paused" | "done" | "skipped";

/** Folds the event stream into what the live view shows: each node's state and a few counters. */
export class RunProgress {
  readonly active = new Map<AgentNode, number>();
  readonly finished = new Map<AgentNode, number>();
  criticScores: number[] = [];
  awaitingApproval = false;
  outcome: "completed" | "rejected" | "failed" | null = null;

  static from(events: readonly RunEvent[]): RunProgress {
    const progress = new RunProgress();
    events.forEach((event) => progress.apply(event));
    return progress;
  }

  static isNode(value: unknown): value is AgentNode {
    return typeof value === "string" && (agentNodes as readonly string[]).includes(value);
  }

  apply(event: RunEvent): void {
    const node = event.data["node"];
    if (event.kind === "nodeStarted" && RunProgress.isNode(node)) {
      this.active.set(node, (this.active.get(node) ?? 0) + 1);
      if (node === "approval") this.awaitingApproval = false;
    } else if (event.kind === "nodeFinished" && RunProgress.isNode(node)) {
      this.active.set(node, Math.max(0, (this.active.get(node) ?? 0) - 1));
      this.finished.set(node, (this.finished.get(node) ?? 0) + 1);
      const score = RunProgress.criticScore(event);
      if (score !== null) this.criticScores.push(score);
    } else if (event.kind === "awaitingApproval") {
      this.awaitingApproval = true;
      // The approval node was interrupted, so it never reports finishing; it is paused instead.
      this.active.set("approval", 0);
    } else if (event.kind === "runFinished") {
      this.outcome = event.data["status"] === "rejected" ? "rejected" : "completed";
    } else if (event.kind === "runFailed") {
      this.outcome = "failed";
    }
  }

  stateOf(node: AgentNode): NodeState {
    if ((this.active.get(node) ?? 0) > 0) return "running";
    if (node === "approval" && this.awaitingApproval) return "paused";
    if ((this.finished.get(node) ?? 0) > 0) return "done";
    // A finished run that never reached a step took another branch, such as no approval for a non-sensitive brief.
    return this.outcome === "completed" || this.outcome === "rejected" ? "skipped" : "waiting";
  }

  timesRun(node: AgentNode): number {
    return this.finished.get(node) ?? 0;
  }

  private static criticScore(event: RunEvent): number | null {
    const update = event.data["update"];
    if (event.data["node"] !== "critic" || typeof update !== "object" || update === null) return null;
    const critique = (update as Record<string, unknown>)["critique"];
    if (typeof critique !== "object" || critique === null) return null;
    const score = (critique as Record<string, unknown>)["score"];
    return typeof score === "number" ? score : null;
  }
}
