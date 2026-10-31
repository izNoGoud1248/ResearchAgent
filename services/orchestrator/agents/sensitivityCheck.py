from typing import Any

from libs.llm.jsonReply import JsonReply
from libs.llm.llmClient import LlmClient
from services.orchestrator.researchState import ResearchState


class SensitivityCheck:
    instructions = (
        "Decide whether a research brief needs human review before release. Sensitive means it gives "
        "operational detail for attacks or weapons, medical or legal advice, or claims about named people. "
        'Return JSON: {"sensitive": bool, "reason": str}'
    )

    def __init__(self, llm: LlmClient):
        self.llm = llm

    async def run(self, state: ResearchState) -> dict[str, Any]:
        if state.get("sensitive"):
            return {"sensitiveReason": "marked sensitive by the user"}
        reply = await self.llm.complete(
            "sensitivity",
            [{"role": "system", "content": self.instructions}, {"role": "user", "content": state["draft"]}],
            runId=state["runId"],
            jsonMode=True,
        )
        parsed = JsonReply.parse(reply.text)
        return {"sensitive": parsed.get("sensitive") is True, "sensitiveReason": str(parsed.get("reason", ""))}

    @staticmethod
    def nextStep(state: ResearchState) -> str:
        return "approval" if state["sensitive"] else "saveNote"
