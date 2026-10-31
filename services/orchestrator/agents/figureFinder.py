import re
from collections import Counter
from typing import Any

from libs.tools.gatewayClient import GatewayClient, ToolCallError
from services.orchestrator.researchState import ResearchState


class FigureFinder:
    """Collects figures from the papers the findings cite most, so the writer can show one or two of them.

    Best effort: a report without figures is still a complete report.
    """

    maxPapers = 4
    # Researchers cite as [arXiv:id] or as a bare [id], so any arXiv id in a claim counts.
    citation = re.compile(r"(\d{4}\.\d{4,5})(?:v\d+)?")

    def __init__(self, tools: GatewayClient):
        self.tools = tools

    async def run(self, state: ResearchState) -> dict[str, Any]:
        cited = Counter(paperId for finding in state["findings"] for claim in finding["claims"] for paperId in self.citation.findall(claim))
        paperIds = [paperId for paperId, _ in cited.most_common(self.maxPapers)]
        if not paperIds:
            return {"figures": []}
        try:
            result = await self.tools.call("writer", state["runId"], state["traceId"], "paper.figures", {"paperIds": paperIds})
        except ToolCallError:
            return {"figures": []}
        return {"figures": result["figures"]}
