from typing import Any

from libs.runEvents import RunEvents
from libs.tools.gatewayClient import GatewayClient
from services.orchestrator.researchState import ResearchState


class NoteSaver:
    def __init__(self, tools: GatewayClient, events: RunEvents):
        self.tools = tools
        self.events = events

    async def run(self, state: ResearchState) -> dict[str, Any]:
        await self.events.publish(state["runId"], "toolCall", agent="writer", tool="notes.save")
        saved = await self.tools.call(
            "writer", state["runId"], state["traceId"], "notes.save", {"title": state["question"][:200], "body": state["draft"]}
        )
        return {"noteId": saved["noteId"]}
