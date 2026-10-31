import type { RunEvent } from "./api/types";

export const agentNodes = [
  "clarify",
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

/** One parallel researcher: the sub-question it works on and what it has done so far. */
export interface ResearcherLane {
  part: number;
  question: string;
  state: "waiting" | "running" | "done";
  toolCalls: number;
  lastAction: string;
  papers: number;
  stopReason: string;
  steps: number;
}

/** Folds the event stream into what the live view shows: each node's state and a few counters. */
export class RunProgress {
  readonly active = new Map<AgentNode, number>();
  readonly finished = new Map<AgentNode, number>();
  criticScores: number[] = [];
  awaitingApproval = false;
  awaitingClarification = false;
  outcome: "completed" | "rejected" | "failed" | null = null;
  readonly lanes = new Map<number, ResearcherLane>();
  reportSkill = "";

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
    this.applyToLane(event);
    if (event.kind === "nodeStarted" && RunProgress.isNode(node)) {
      this.active.set(node, (this.active.get(node) ?? 0) + 1);
      if (node === "approval") this.awaitingApproval = false;
      if (node === "planner") this.awaitingClarification = false;
    } else if (event.kind === "nodeFinished" && RunProgress.isNode(node)) {
      this.active.set(node, Math.max(0, (this.active.get(node) ?? 0) - 1));
      this.finished.set(node, (this.finished.get(node) ?? 0) + 1);
      const score = RunProgress.criticScore(event);
      if (score !== null) this.criticScores.push(score);
    } else if (event.kind === "awaitingApproval") {
      this.awaitingApproval = true;
      // The approval node was interrupted, so it never reports finishing; it is paused instead.
      this.active.set("approval", 0);
    } else if (event.kind === "awaitingClarification") {
      this.awaitingClarification = true;
    } else if (event.kind === "runFinished") {
      this.outcome = event.data["status"] === "rejected" ? "rejected" : "completed";
    } else if (event.kind === "runFailed") {
      this.outcome = "failed";
    }
  }

  /** Researcher lanes in sub-question order. Older runs carry no sub-question numbers and have none. */
  researcherLanes(): ResearcherLane[] {
    const lanes = [...this.lanes.values()].sort((first, second) => first.part - second.part);
    return lanes.some((lane) => lane.question) ? lanes : [];
  }

  private applyToLane(event: RunEvent): void {
    const data = event.data;
    if (event.kind === "nodeFinished" && data["node"] === "planner") {
      const update = data["update"];
      const fields = typeof update === "object" && update !== null ? (update as Record<string, unknown>) : {};
      const planned = fields["plan"];
      if (typeof fields["reportSkill"] === "string") this.reportSkill = fields["reportSkill"];
      for (let part = 1; typeof planned === "number" && part <= planned; part++) this.lane(part);
      return;
    }
    const part = data["part"];
    if (typeof part !== "number") return;
    const lane = this.lane(part);
    if (typeof data["question"] === "string") lane.question = data["question"];
    if (event.kind === "nodeStarted") lane.state = "running";
    if (event.kind === "nodeFinished") {
      lane.state = "done";
      if (typeof data["papers"] === "number") lane.papers = data["papers"];
    }
    if (event.kind === "toolCall") {
      lane.toolCalls += 1;
      lane.lastAction = `${String(data["tool"] ?? "")}${data["query"] ? `: ${String(data["query"])}` : ""}`;
    }
    if (event.kind === "agentFinished") {
      if (typeof data["stopReason"] === "string") lane.stopReason = data["stopReason"];
      if (typeof data["steps"] === "number") lane.steps = data["steps"];
    }
  }

  private lane(part: number): ResearcherLane {
    const existing = this.lanes.get(part);
    if (existing) return existing;
    const created: ResearcherLane = { part, question: "", state: "waiting", toolCalls: 0, lastAction: "", papers: 0, stopReason: "", steps: 0 };
    this.lanes.set(part, created);
    return created;
  }

  stateOf(node: AgentNode): NodeState {
    if ((this.active.get(node) ?? 0) > 0) return "running";
    if (node === "approval" && this.awaitingApproval) return "paused";
    if (node === "clarify" && this.awaitingClarification) return "paused";
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
