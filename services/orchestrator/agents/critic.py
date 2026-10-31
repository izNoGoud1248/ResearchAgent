from typing import Any

from libs.llm.jsonReply import JsonReply
from libs.llm.llmClient import LlmClient
from services.orchestrator.researchState import ResearchState


class Critic:
    passingScore = 7
    maxDrafts = 3

    instructions = (
        "You review a research brief. Score it 1 to 10 on: answers the question, every claim cited as [arXiv:id], "
        "no overclaiming, clear structure. Be demanding but fair. "
        'Return JSON: {"score": int, "feedback": str} with concrete fixes in feedback.'
    )

    def __init__(self, llm: LlmClient):
        self.llm = llm

    async def run(self, state: ResearchState) -> dict[str, Any]:
        reply = await self.llm.complete(
            "critic",
            [
                {"role": "system", "content": self.instructions},
                {"role": "user", "content": f"Question: {state['question']}\n\nBrief:\n{state['draft']}"},
            ],
            runId=state["runId"],
            jsonMode=True,
        )
        parsed = JsonReply.parse(reply.text)
        score = parsed.get("score")
        return {"critique": {
            "score": int(score) if isinstance(score, (int, float)) else 0,
            "feedback": str(parsed.get("feedback", "")),
        }}

    def nextStep(self, state: ResearchState) -> str:
        if state["critique"]["score"] >= self.passingScore or state["drafts"] >= self.maxDrafts:
            return "sensitivity"
        return "writer"
