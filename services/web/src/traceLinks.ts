import type { ToolLinks } from "./api/types";

/** Deep links for one trace id into each observability tool. Langfuse is optional. */
export class TraceLinks {
  static readonly kibanaDataView = "researchdesk-logs";

  static forTrace(links: ToolLinks, traceId: string): { label: string; href: string }[] {
    const result = [
      { label: "Trace in Jaeger", href: `${links.jaeger}/trace/${traceId}` },
      { label: "Logs in Kibana", href: TraceLinks.kibana(links.kibana, traceId) },
    ];
    if (links.langfuse) {
      result.push({ label: "LLM calls in Langfuse", href: `${links.langfuse.replace(/\/$/, "")}/traces/${traceId}` });
    }
    return result;
  }

  private static kibana(base: string, traceId: string): string {
    const appState = `(dataSource:(dataViewId:'${TraceLinks.kibanaDataView}',type:dataView),query:(language:kuery,query:'app.traceId:"${traceId}"'))`;
    const globalState = "(time:(from:now-7d,to:now))";
    return `${base}/app/discover#/?_g=${encodeURIComponent(globalState)}&_a=${encodeURIComponent(appState)}`;
  }
}
