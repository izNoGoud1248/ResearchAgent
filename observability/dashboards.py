import json
from typing import Any

Column = dict[str, Any]
SavedObject = dict[str, Any]

# Kibana migrates imported objects from the version they claim. Without these it assumes 7.x and fails.
# Values for Kibana 8.17; read them from a freshly created object when upgrading Kibana.
coreMigrationVersion = "8.8.0"
lensVersion = "8.9.0"
dashboardVersion = "10.2.0"


class Lens:
    """Builds Kibana Lens visualizations as saved objects. One layer per visualization, on one data view."""

    def __init__(self, dataViewId: str):
        self.dataViewId = dataViewId

    @staticmethod
    def dateHistogram() -> Column:
        return {
            "label": "Time", "customLabel": True, "dataType": "date", "operationType": "date_histogram",
            "sourceField": "@timestamp", "isBucketed": True, "scale": "interval",
            "params": {"interval": "auto", "includeEmptyRows": True, "dropPartials": False},
        }

    @staticmethod
    def count(label: str) -> Column:
        return {
            "label": label, "customLabel": True, "dataType": "number", "operationType": "count",
            "sourceField": "___records___", "isBucketed": False, "scale": "ratio", "params": {"emptyAsNull": False},
        }

    @staticmethod
    def measure(operation: str, field: str, label: str, decimals: int = 0, percentile: int | None = None) -> Column:
        params: dict[str, Any] = {"emptyAsNull": False, "format": {"id": "number", "params": {"decimals": decimals}}}
        if percentile is not None:
            params["percentile"] = percentile
        return {
            "label": label, "customLabel": True, "dataType": "number", "operationType": operation,
            "sourceField": field, "isBucketed": False, "scale": "ratio", "params": params,
        }

    @staticmethod
    def terms(field: str, label: str, size: int, orderBy: str | None = None) -> Column:
        order = {"type": "column", "columnId": orderBy} if orderBy else {"type": "alphabetical", "fallback": True}
        return {
            "label": label, "customLabel": True, "dataType": "string", "operationType": "terms",
            "sourceField": field, "isBucketed": True, "scale": "ordinal",
            "params": {
                "size": size, "orderBy": order, "orderDirection": "desc", "otherBucket": False,
                "missingBucket": False, "parentFormat": {"id": "terms"},
            },
        }

    def visualization(
        self, objectId: str, title: str, kind: str, columns: dict[str, Column], visualization: dict[str, Any], query: str
    ) -> SavedObject:
        return {
            "type": "lens",
            "id": objectId,
            "coreMigrationVersion": coreMigrationVersion,
            "typeMigrationVersion": lensVersion,
            "attributes": {
                "title": title,
                "description": "",
                "visualizationType": kind,
                "state": {
                    "datasourceStates": {
                        "formBased": {
                            "layers": {
                                "layer1": {"columns": columns, "columnOrder": list(columns), "incompleteColumns": {}, "sampling": 1}
                            }
                        }
                    },
                    "visualization": visualization,
                    "query": {"query": query, "language": "kuery"},
                    "filters": [],
                    "internalReferences": [],
                    "adHocDataViews": {},
                },
            },
            "references": [{"type": "index-pattern", "id": self.dataViewId, "name": "indexpattern-datasource-layer-layer1"}],
        }

    def metric(self, objectId: str, title: str, value: Column, query: str) -> SavedObject:
        return self.visualization(
            objectId, title, "lnsMetric", {"value": value},
            {"layerId": "layer1", "layerType": "data", "metricAccessor": "value"}, query,
        )

    def bars(
        self,
        objectId: str,
        title: str,
        query: str,
        metrics: dict[str, Column],
        xAxis: tuple[str, Column] | None = None,
        split: tuple[str, Column] | None = None,
        horizontal: bool = False,
        stacked: bool = True,
    ) -> SavedObject:
        columns: dict[str, Column] = {}
        if split:
            columns[split[0]] = split[1]
        if xAxis:
            columns[xAxis[0]] = xAxis[1]
        columns |= metrics
        seriesType = ("bar_horizontal" if horizontal else "bar") + ("_stacked" if stacked else "")
        layer: dict[str, Any] = {"layerId": "layer1", "layerType": "data", "seriesType": seriesType, "accessors": list(metrics)}
        if xAxis:
            layer["xAccessor"] = xAxis[0]
        if split:
            layer["splitAccessor"] = split[0]
        return self.visualization(
            objectId, title, "lnsXY", columns,
            {
                "legend": {"isVisible": True, "position": "bottom"},
                "valueLabels": "hide",
                "preferredSeriesType": seriesType,
                "layers": [layer],
            },
            query,
        )

    def donut(self, objectId: str, title: str, group: Column, value: Column, query: str) -> SavedObject:
        return self.visualization(
            objectId, title, "lnsPie", {"group": group, "value": value},
            {
                "shape": "donut",
                "layers": [{
                    "layerId": "layer1", "layerType": "data", "primaryGroups": ["group"], "metrics": ["value"],
                    "numberDisplay": "value", "categoryDisplay": "default", "legendDisplay": "show", "nestedLegend": False,
                }],
            },
            query,
        )

    def table(self, objectId: str, title: str, columns: dict[str, Column], query: str) -> SavedObject:
        return self.visualization(
            objectId, title, "lnsDatatable", columns,
            {"layerId": "layer1", "layerType": "data", "columns": [{"columnId": columnId} for columnId in columns]},
            query,
        )


class Dashboard:
    """Lays out panels on Kibana's 48-column grid, row by row, and builds the dashboard saved object."""

    def __init__(self, objectId: str, title: str, description: str):
        self.objectId = objectId
        self.title = title
        self.description = description
        self.panels: list[tuple[SavedObject, int, int, int, int]] = []
        self.cursorY = 0

    def row(self, height: int, *items: tuple[SavedObject, int]) -> "Dashboard":
        x = 0
        for visualization, width in items:
            self.panels.append((visualization, x, self.cursorY, width, height))
            x += width
        self.cursorY += height
        return self

    def savedObjects(self) -> list[SavedObject]:
        panels = []
        references = []
        for index, (visualization, x, y, width, height) in enumerate(self.panels):
            panelId = f"p{index}"
            panels.append({
                "type": "lens",
                "gridData": {"x": x, "y": y, "w": width, "h": height, "i": panelId},
                "panelIndex": panelId,
                "embeddableConfig": {"enhancements": {}},
                "panelRefName": f"panel_{panelId}",
            })
            references.append({"name": f"{panelId}:panel_{panelId}", "type": "lens", "id": visualization["id"]})
        dashboard = {
            "type": "dashboard",
            "id": self.objectId,
            "coreMigrationVersion": coreMigrationVersion,
            "typeMigrationVersion": dashboardVersion,
            "attributes": {
                "title": self.title,
                "description": self.description,
                "timeRestore": True,
                "timeFrom": "now-7d",
                "timeTo": "now",
                "refreshInterval": {"pause": False, "value": 30000},
                "optionsJSON": json.dumps({"useMargins": True, "syncColors": True, "syncCursor": True, "hidePanelTitles": False}),
                "panelsJSON": json.dumps(panels),
                "kibanaSavedObjectMeta": {"searchSourceJSON": json.dumps({"query": {"query": "", "language": "kuery"}, "filter": []})},
            },
            "references": references,
        }
        return [visualization for visualization, *_ in self.panels] + [dashboard]


class ResearchDeskDashboards:
    """The two dashboards: operations and cost, and security and audit. Kibana answers trends; Jaeger answers one run."""

    piiKinds = ("email", "phone", "card", "ssn", "apiKey", "ipAddress")

    def __init__(self, dataViewId: str):
        self.lens = Lens(dataViewId)

    def operations(self) -> Dashboard:
        lens = self.lens
        finished = 'app.message.keyword:"run finished"'
        return (
            Dashboard(
                "researchdesk-operations",
                "ResearchDesk: operations and cost",
                "Runs, outcomes, spend, approvals, tool latency and errors across all runs.",
            )
            .row(
                7,
                (lens.metric("rd-ops-queued", "Runs started", lens.count("Runs"), 'app.message.keyword:"run queued"'), 12),
                (lens.metric("rd-ops-finished", "Runs finished", lens.count("Runs"), finished), 12),
                (lens.metric("rd-ops-spend", "Spend (USD)", lens.measure("sum", "app.usd", "USD", 4), finished), 12),
                (lens.metric("rd-ops-average", "Average cost per run (USD)", lens.measure("average", "app.usd", "USD", 4), finished), 12),
            )
            .row(
                13,
                (lens.bars(
                    "rd-ops-outcomes", "Runs by outcome", finished, {"runs": lens.count("Runs")},
                    xAxis=("time", lens.dateHistogram()), split=("status", lens.terms("app.status.keyword", "Outcome", 5, "runs")),
                ), 24),
                (lens.bars(
                    "rd-ops-spendOverTime", "Spend over time (USD)", finished,
                    {"usd": lens.measure("sum", "app.usd", "USD", 4)}, xAxis=("time", lens.dateHistogram()),
                ), 24),
            )
            .row(
                13,
                (lens.donut(
                    "rd-ops-decisions", "Approval decisions", lens.terms("app.action.keyword", "Decision", 5, "value"),
                    lens.count("Decisions"), 'app.message.keyword:"approval decision"',
                ), 16),
                (lens.bars(
                    "rd-ops-latency", "Tool latency by tool (ms)", "app.event.keyword:audit",
                    {
                        "median": lens.measure("median", "app.ms", "Median ms"),
                        "p95": lens.measure("percentile", "app.ms", "95th percentile ms", percentile=95),
                    },
                    xAxis=("tool", lens.terms("app.tool.keyword", "Tool", 10, "p95")), stacked=False,
                ), 32),
            )
            .row(
                12,
                (lens.table(
                    "rd-ops-runs", "Finished runs (trace id opens Jaeger)",
                    {
                        "run": lens.terms("app.runId.keyword", "Run", 50, "usd"),
                        "status": lens.terms("app.status.keyword", "Outcome", 5),
                        "trace": lens.terms("app.traceId.keyword", "Trace", 5),
                        "usd": lens.measure("sum", "app.usd", "USD", 4),
                    },
                    finished,
                ), 28),
                (lens.table(
                    "rd-ops-errors", "Errors",
                    {
                        "service": lens.terms("app.service.keyword", "Service", 10, "count"),
                        "message": lens.terms("app.message.keyword", "Message", 20, "count"),
                        "trace": lens.terms("app.traceId.keyword", "Trace", 20, "count"),
                        "count": lens.count("Count"),
                    },
                    "app.level.keyword:error",
                ), 20),
            )
        )

    def security(self) -> Dashboard:
        lens = self.lens
        audit = "app.event.keyword:audit"
        return (
            Dashboard(
                "researchdesk-security",
                "ResearchDesk: security and audit",
                "Every tool call through the MCP gateway: decisions, denial reasons, agents, PII redaction and fact-check results.",
            )
            .row(
                7,
                (lens.metric("rd-sec-calls", "Tool calls", lens.count("Calls"), audit), 12),
                (lens.metric("rd-sec-denied", "Denied", lens.count("Denied"), f"{audit} and app.outcome.keyword:denied"), 12),
                (lens.metric("rd-sec-failed", "Failed", lens.count("Failed"), f"{audit} and app.outcome.keyword:failed"), 12),
                (lens.metric("rd-sec-agents", "Distinct agents", lens.measure("unique_count", "app.agent.keyword", "Agents"), audit), 12),
            )
            .row(
                13,
                (lens.bars(
                    "rd-sec-outcomes", "Gateway decisions over time", audit, {"calls": lens.count("Calls")},
                    xAxis=("time", lens.dateHistogram()), split=("outcome", lens.terms("app.outcome.keyword", "Outcome", 3, "calls")),
                ), 24),
                (lens.bars(
                    "rd-sec-reasons", "Why calls were refused", f"{audit} and not app.outcome.keyword:allowed",
                    {"calls": lens.count("Calls")}, xAxis=("reason", lens.terms("app.reason.keyword", "Reason", 8, "calls")),
                    horizontal=True,
                ), 24),
            )
            .row(
                13,
                (lens.bars(
                    "rd-sec-agentsByOutcome", "Calls by agent", audit, {"calls": lens.count("Calls")},
                    xAxis=("agent", lens.terms("app.agent.keyword", "Agent", 8, "calls")),
                    split=("outcome", lens.terms("app.outcome.keyword", "Outcome", 3, "calls")),
                ), 16),
                (lens.bars(
                    "rd-sec-pii", "PII redacted by type", audit,
                    {kind: lens.measure("sum", f"app.pii.{kind}", kind) for kind in self.piiKinds}, stacked=False,
                ), 16),
                (lens.bars(
                    "rd-sec-verdicts", "Fact-check verdicts", 'app.message.keyword:"claims checked"',
                    {
                        "supported": lens.measure("sum", "app.supported", "Supported"),
                        "unclear": lens.measure("sum", "app.unclear", "Unclear"),
                        "unsupported": lens.measure("sum", "app.unsupported", "Unsupported"),
                    },
                    stacked=False,
                ), 16),
            )
            .row(
                14,
                (lens.table(
                    "rd-sec-drilldown", "Tool calls (trace id opens Jaeger, run opens the app)",
                    {
                        "agent": lens.terms("app.agent.keyword", "Agent", 10, "count"),
                        "tool": lens.terms("app.tool.keyword", "Tool", 10, "count"),
                        "outcome": lens.terms("app.outcome.keyword", "Outcome", 3, "count"),
                        "reason": lens.terms("app.reason.keyword", "Reason", 10, "count"),
                        "run": lens.terms("app.run.keyword", "Run", 20, "count"),
                        "trace": lens.terms("app.trace.keyword", "Trace", 20, "count"),
                        "count": lens.count("Calls"),
                    },
                    audit,
                ), 48),
            )
        )

    def savedObjects(self) -> list[SavedObject]:
        return self.operations().savedObjects() + self.security().savedObjects()
