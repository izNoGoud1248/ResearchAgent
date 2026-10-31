import json
import time

import httpx

from libs.settings import Settings
from observability.dashboards import ResearchDeskDashboards


class LogRetention:
    """Deletes log and audit indices after a set number of days, and pins the types of numeric fields."""

    policyName = "researchdesk-retention"
    templateName = "researchdesk"
    indexPattern = "researchdesk-*"
    piiKinds = ResearchDeskDashboards.piiKinds

    def __init__(self, elasticsearchUrl: str, days: int):
        self.client = httpx.Client(base_url=elasticsearchUrl, timeout=30)
        self.days = days

    def mappings(self) -> dict:
        # Dynamic mapping takes its type from the first value it sees: 0 would make usd a long. Pin them instead.
        numbers = {"usd": {"type": "float"}, "ms": {"type": "long"}, "supported": {"type": "long"},
                   "unclear": {"type": "long"}, "unsupported": {"type": "long"}, "revision": {"type": "long"}}
        pii = {"properties": {kind: {"type": "long"} for kind in self.piiKinds}}
        return {"properties": {"app": {"properties": numbers | {"pii": pii}}}}

    def run(self) -> None:
        self.client.put(
            f"/_ilm/policy/{self.policyName}",
            json={"policy": {"phases": {"hot": {"actions": {}}, "delete": {"min_age": f"{self.days}d", "actions": {"delete": {}}}}}},
        ).raise_for_status()
        self.client.put(
            f"/_index_template/{self.templateName}",
            json={
                "index_patterns": [self.indexPattern],
                "priority": 200,
                "template": {"settings": {"index.lifecycle.name": self.policyName}, "mappings": self.mappings()},
            },
        ).raise_for_status()
        # Indices created before the template existed get the policy and mappings too.
        existing = self.client.get(f"/_cat/indices/{self.indexPattern}", params={"h": "index", "format": "json"}).json()
        if existing:
            self.client.put(f"/{self.indexPattern}/_settings", json={"index.lifecycle.name": self.policyName}).raise_for_status()
            self.client.put(f"/{self.indexPattern}/_mapping", json=self.mappings()).raise_for_status()
        print(f"retention: delete after {self.days} days, applied to {len(existing)} existing indices")


class KibanaSetup:
    """Creates data views, link formats and dashboards. Safe to run again: everything is overwritten in place."""

    logsView = "researchdesk-logs"
    dataViews = {
        logsView: ("researchdesk-*", "ResearchDesk logs and audit"),
        "researchdesk-audit": ("researchdesk-audit-*", "ResearchDesk audit"),
    }

    def __init__(self, settings: Settings, webUrl: str = "http://localhost:5173"):
        self.settings = settings
        self.webUrl = webUrl
        self.client = httpx.Client(base_url=settings.kibanaUrl, headers={"kbn-xsrf": "true"}, timeout=60)

    def run(self) -> None:
        self.waitUntilReady()
        LogRetention(self.settings.elasticsearchUrl, self.settings.logRetentionDays).run()
        for viewId, (pattern, name) in self.dataViews.items():
            self.client.post(
                "/api/data_views/data_view",
                json={"data_view": {"id": viewId, "title": pattern, "name": name, "timeFieldName": "@timestamp"}, "override": True},
            ).raise_for_status()
            self.addLinks(viewId)
            print(f"data view {viewId} -> {pattern}")
        self.importDashboards()

    def addLinks(self, viewId: str) -> None:
        jaeger = {"id": "url", "params": {"urlTemplate": f"{self.settings.jaegerUrl}/trace/{{{{value}}}}", "labelTemplate": "{{value}}"}}
        run = {"id": "url", "params": {"urlTemplate": f"{self.webUrl}/#/runs/{{{{value}}}}", "labelTemplate": "{{value}}"}}
        fields = {
            name: {"format": format}
            for name, format in (
                ("app.traceId.keyword", jaeger), ("app.trace.keyword", jaeger),
                ("app.runId.keyword", run), ("app.run.keyword", run),
            )
        }
        self.client.post(f"/api/data_views/data_view/{viewId}/fields", json={"fields": fields}).raise_for_status()

    def importDashboards(self) -> None:
        objects = ResearchDeskDashboards(self.logsView).savedObjects()
        body = "\n".join(json.dumps(item) for item in objects)
        response = self.client.post(
            "/api/saved_objects/_import",
            params={"overwrite": "true"},
            files={"file": ("researchdesk.ndjson", body.encode(), "application/ndjson")},
        )
        response.raise_for_status()
        result = response.json()
        if not result.get("success"):
            raise RuntimeError(f"dashboard import failed: {json.dumps(result.get('errors'))[:1500]}")
        print(f"imported {result['successCount']} saved objects")
        for dashboardId in ("researchdesk-operations", "researchdesk-security"):
            print(f"  {self.settings.kibanaUrl}/app/dashboards#/view/{dashboardId}")

    def waitUntilReady(self, attempts: int = 60) -> None:
        for _ in range(attempts):
            try:
                if self.client.get("/api/status").json()["status"]["overall"]["level"] == "available":
                    return
            except (httpx.HTTPError, KeyError, ValueError):
                pass
            time.sleep(5)
        raise TimeoutError("Kibana did not become available")


if __name__ == "__main__":
    KibanaSetup(Settings()).run()
