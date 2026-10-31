from typing import Any

from libs.telemetry.jsonLogger import JsonLogger
from libs.tools.gatewayClient import GatewayClient


class PaperShelf:
    """Adds papers an agent found to the library. Best effort: a library outage must not fail the research."""

    def __init__(self, gateway: GatewayClient):
        self.gateway = gateway
        self.log = JsonLogger("paperShelf")

    async def add(self, agent: str, runId: str, traceId: str, papers: list[dict[str, Any]]) -> None:
        if not papers:
            return
        entries = [
            {"id": paper["id"], "title": paper["title"], "published": paper.get("published"), "summary": paper["summary"]}
            for paper in papers
        ]
        try:
            await self.gateway.call(agent, runId, traceId, "library.add", {"papers": entries})
        except Exception as error:  # network, refusal or library error: research continues without it
            self.log.warning("library add failed", runId=runId, error=f"{type(error).__name__}: {error}"[:300])
