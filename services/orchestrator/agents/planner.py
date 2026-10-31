from typing import Any

from libs.llm.jsonReply import JsonReply
from libs.llm.llmClient import LlmClient
from services.orchestrator.researchState import ResearchState


class Planner:
    maxParts = 4

    instructions = (
        "You plan literature research. Split the user's question into 2 to 4 focused sub-questions. "
        "For each, give a short keyword query suited to the arXiv search API (3 to 6 words, no quotes). "
        'Return JSON: {"plan": [{"question": str, "searchQuery": str}]}'
    )

    def __init__(self, llm: LlmClient):
        self.llm = llm

    async def run(self, state: ResearchState) -> dict[str, Any]:
        reply = await self.llm.complete(
            "planner",
            [{"role": "system", "content": self.instructions}, {"role": "user", "content": self.request(state)}],
            runId=state["runId"],
            jsonMode=True,
        )
        plan = [
            {"question": str(part["question"]), "searchQuery": str(part["searchQuery"])}
            for part in JsonReply.parse(reply.text).get("plan", [])
            if isinstance(part, dict) and part.get("question") and part.get("searchQuery")
        ][: self.maxParts]
        # A plan the model failed to produce still lets the run continue with the original question.
        return {"plan": plan or [{"question": state["question"], "searchQuery": state["question"][:120]}]}

    @staticmethod
    def request(state: ResearchState) -> str:
        # What the clarifier settled about the question shapes the plan.
        parts = [state["question"]]
        if state.get("clarification"):
            parts.append(f"The user clarified: {state['clarification']}")
        if state.get("assumption"):
            parts.append(f"Working assumption: {state['assumption']}")
        return "\n".join(parts)
