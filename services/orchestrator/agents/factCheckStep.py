from typing import Any

from libs.runEvents import RunEvents
from libs.tools.a2aClient import A2aClient
from services.orchestrator.researchState import ResearchState


class FactCheckStep:
    """Sends the researchers' claims to the separate Fact-Checker agent over A2A."""

    def __init__(self, factChecker: A2aClient, events: RunEvents):
        self.factChecker = factChecker
        self.events = events

    async def run(self, state: ResearchState) -> dict[str, Any]:
        claims = [claim for finding in state["findings"] for claim in finding["claims"]]
        if not claims:
            return {"verdicts": []}
        await self.events.publish(state["runId"], "a2aCall", agent="factChecker", claims=len(claims))
        answer = await self.factChecker.ask({"question": state["question"], "claims": claims}, state["runId"], state["traceId"])
        return {"verdicts": answer["verdicts"]}
