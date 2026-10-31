import type { RunEvent } from "./api/types";
import { Formatter } from "./formatter";

/** Turns raw run events into one readable line each for the live feed. */
export class EventDescriber {
  static describe(event: RunEvent): string {
    const data = event.data;
    const node = EventDescriber.text(data["node"]);
    switch (event.kind) {
      case "runStarted":
        return data["job"] === "resume" ? "Run resumed after your input" : "Run picked up by a worker";
      case "nodeStarted":
        return `${node}${EventDescriber.part(data)} started`;
      case "nodeFinished":
        return `${node}${EventDescriber.part(data)} finished${EventDescriber.finishedDetail(data)}`;
      case "toolCall":
        return `${EventDescriber.text(data["agent"])}${EventDescriber.part(data)} called ${EventDescriber.text(data["tool"])} through the MCP gateway${
          data["query"] ? `: "${EventDescriber.text(data["query"])}"` : ""
        }`;
      case "a2aCall":
        return `Sent ${EventDescriber.text(data["claims"])} claims to the Fact-Checker over A2A`;
      case "awaitingClarification":
        return `Asked you: ${EventDescriber.text(data["question"])}`;
      case "awaitingApproval":
        if (typeof data["revision"] === "number" && data["revision"] > 0) {
          return `Revised draft ${data["revision"]} ready for review`;
        }
        return `Waiting for human approval${data["reason"] ? ` (${EventDescriber.text(data["reason"])})` : ""}`;
      case "runFinished":
        return `Run ${EventDescriber.text(data["status"])}`;
      case "runFailed":
        return `Run failed: ${EventDescriber.text(data["error"])}`;
      default:
        return event.kind;
    }
  }

  private static finishedDetail(data: Record<string, unknown>): string {
    const update = data["update"];
    if (typeof update !== "object" || update === null) return "";
    const fields = update as Record<string, unknown>;
    if (typeof fields["plan"] === "number") {
      const style = typeof fields["reportSkill"] === "string" ? `, ${Formatter.skillName(fields["reportSkill"]).toLowerCase()} style` : "";
      return `: ${fields["plan"]} sub-questions${style}`;
    }
    if (typeof fields["findings"] === "number") return `: ${fields["findings"]} finding`;
    if (typeof fields["verdicts"] === "number") return `: ${fields["verdicts"]} verdicts`;
    if (typeof fields["drafts"] === "number") return `: draft ${fields["drafts"]}`;
    const critique = fields["critique"];
    if (typeof critique === "object" && critique !== null && "score" in critique) {
      return `: scored ${EventDescriber.text(critique.score)}/10`;
    }
    if (typeof fields["sensitive"] === "boolean") return fields["sensitive"] ? ": needs review" : ": not sensitive";
    const action = fields["reviewAction"];
    if (action === "revise") return ": changes requested, back to the writer";
    if (action === "approve") return ": approved";
    if (action === "reject") return ": rejected";
    if (typeof fields["noteId"] === "string") return ": report saved";
    return "";
  }

  private static part(data: Record<string, unknown>): string {
    return typeof data["part"] === "number" ? ` #${data["part"]}` : "";
  }

  private static text(value: unknown): string {
    return typeof value === "string" || typeof value === "number" ? String(value) : "";
  }
}
