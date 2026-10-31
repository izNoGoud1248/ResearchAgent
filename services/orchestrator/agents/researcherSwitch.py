from typing import Any

from services.orchestrator.agents.agentResearcher import AgentResearcher
from services.orchestrator.agents.researcher import Researcher
from services.orchestrator.researchState import ResearchTask


class ResearcherSwitch:
    """Picks the researcher per run: the fixed workflow (search once, summarize) or the agent (decides its own steps)."""

    modes = ("workflow", "agent")

    def __init__(self, workflow: Researcher, agent: AgentResearcher):
        self.workflow = workflow
        self.agent = agent

    async def run(self, task: ResearchTask) -> dict[str, Any]:
        return await (self.agent if task.get("mode") == "agent" else self.workflow).run(task)
