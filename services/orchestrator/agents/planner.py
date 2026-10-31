from typing import Any

from libs.llm.jsonReply import JsonReply
from libs.llm.llmClient import LlmClient
from services.orchestrator.reportSkills import ReportSkills
from services.orchestrator.researchState import ResearchState


class Planner:
    maxParts = 4

    instructions = (
        "You plan literature research. Split the user's question into 2 to 4 focused sub-questions. "
        "For each, give a short keyword query suited to the arXiv search API (3 to 6 words, no quotes). "
        "When a sub-question names a specific method or model, put its field in the query too, for example "
        "'EAGLE speculative decoding' rather than 'EAGLE': bare names also match papers from unrelated fields. "
        "Also pick the report style that best fits the question from this list:\n{skills}\n"
        "A question that names two or more methods or models, or asks which is best, fastest or biggest, is a comparison. "
        'Return JSON: {{"skill": str, "plan": [{{"question": str, "searchQuery": str}}]}}'
    )

    def __init__(self, llm: LlmClient, skills: ReportSkills):
        self.llm = llm
        self.skills = skills

    async def run(self, state: ResearchState) -> dict[str, Any]:
        reply = await self.llm.complete(
            "planner",
            [{"role": "system", "content": self.instructions.format(skills=self.skills.menu())}, {"role": "user", "content": self.request(state)}],
            runId=state["runId"],
            jsonMode=True,
        )
        parsed = JsonReply.parse(reply.text)
        plan = [
            {"question": str(part["question"]), "searchQuery": str(part["searchQuery"])}
            for part in parsed.get("plan", [])
            if isinstance(part, dict) and part.get("question") and part.get("searchQuery")
        ][: self.maxParts]
        # A plan the model failed to produce still lets the run continue with the original question.
        return {
            "plan": plan or [{"question": state["question"], "searchQuery": state["question"][:120]}],
            # An unknown or missing choice falls back to the default style.
            "reportSkill": self.skills.get(str(parsed.get("skill", ""))).name,
        }

    @staticmethod
    def request(state: ResearchState) -> str:
        # What the clarifier settled about the question shapes the plan.
        parts = [state["question"]]
        if state.get("clarification"):
            parts.append(f"The user clarified: {state['clarification']}")
        if state.get("assumption"):
            parts.append(f"Working assumption: {state['assumption']}")
        return "\n".join(parts)
