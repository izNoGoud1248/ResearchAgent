import type { CostTotal } from "./api/types";

export class Formatter {
  static usd(value: number): string {
    if (value === 0) return "$0";
    return value >= 1 ? `$${value.toFixed(2)}` : `$${value.toFixed(value >= 0.1 ? 2 : 3)}`;
  }

  static milliseconds(value: number): string {
    return value >= 1000 ? `${(value / 1000).toFixed(1)} s` : `${Math.round(value)} ms`;
  }

  /** Kibana dashboards loaded by observability/kibanaSetup.py, by their saved-object ids. */
  static kibanaDashboard(kibana: string, id: "researchdesk-operations" | "researchdesk-security"): string {
    return `${kibana}/app/dashboards#/view/${id}?_g=(time:(from:now-7d,to:now))`;
  }

  /** Skill folder names are camelCase, such as comparisonReport; shown as "Comparison report". */
  static skillName(name: string): string {
    const words = name.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase();
    return words.charAt(0).toUpperCase() + words.slice(1);
  }

  static time(iso: string): string {
    return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
  }

  /** Redis stream ids start with the millisecond timestamp the event was written. */
  static streamTime(eventId: string): string {
    const millis = Number(eventId.split("-")[0]);
    return Number.isFinite(millis) ? new Date(millis).toLocaleTimeString(undefined, { hour12: false }) : "";
  }

  static duration(startIso: string, endIso: string): string {
    const seconds = Math.max(0, Math.round((Date.parse(endIso) - Date.parse(startIso)) / 1000));
    return seconds < 60 ? `${seconds}s` : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  }

  static cost(cost: CostTotal): string {
    return `$${(cost.usd ?? 0).toFixed(4)}`;
  }

  static tokens(cost: CostTotal): string {
    const total = (cost.inputTokens ?? 0) + (cost.outputTokens ?? 0);
    return total.toLocaleString();
  }

  static models(cost: CostTotal): string {
    const names = Object.keys(cost)
      .filter((key) => key.startsWith("calls:"))
      .map((key) => `${key.slice(6)} x${cost[key as `calls:${string}`]}`);
    return names.join(", ") || "none";
  }

  static percent(ratio: number): string {
    return `${Math.round(ratio * 100)}%`;
  }
}
