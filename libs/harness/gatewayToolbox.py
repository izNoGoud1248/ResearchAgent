import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from libs.harness.harnessTool import HarnessTool, ToolRefused
from libs.tools.gatewayClient import GatewayClient, ToolCallError


@dataclass(frozen=True)
class ToolView:
    """How one gateway tool is presented to a model: what part of the result it sees, and its one-line digest."""

    shape: Callable[[Any], Any]
    digest: Callable[[Any], str]
    # Sees every raw result; may be async (for example to store what a search found).
    observe: Callable[[Any], Any] | None = None
    # Replaces the gateway's generic description: when to use a tool depends on the agent and its other tools.
    description: str | None = None


class GatewayToolbox:
    """Turns the MCP gateway's tools into harness tools for one agent.

    Tools are discovered from the gateway when the run starts, so adding a gateway tool needs no change here.
    The view list only decides what this agent is offered; the gateway still enforces what it may call.
    """

    def __init__(self, gateway: GatewayClient, agent: str, runId: str, traceId: str):
        self.gateway = gateway
        self.agent = agent
        self.runId = runId
        self.traceId = traceId

    @staticmethod
    def functionName(mcpName: str) -> str:
        # OpenAI function names allow letters, digits, - and _, so arxiv.search becomes arxivSearch.
        first, *rest = mcpName.split(".")
        return first + "".join(part[:1].upper() + part[1:] for part in rest)

    async def tools(self, views: dict[str, ToolView]) -> list[HarnessTool]:
        listed = await self.gateway.listTools(self.agent, self.runId, self.traceId)
        return [
            HarnessTool(
                name=self.functionName(tool["name"]),
                description=views[tool["name"]].description or tool["description"],
                parameters=tool["inputSchema"],
                run=self.runner(tool["name"], views[tool["name"]]),
                digest=views[tool["name"]].digest,
            )
            for tool in listed
            if tool["name"] in views
        ]

    def runner(self, mcpName: str, view: ToolView) -> Callable[[dict[str, Any]], Any]:
        async def run(arguments: dict[str, Any]) -> Any:
            try:
                result = await self.gateway.call(self.agent, self.runId, self.traceId, mcpName, arguments)
            except ToolCallError as error:
                raise ToolRefused(str(error)) from None
            if view.observe:
                outcome = view.observe(result)
                if inspect.isawaitable(outcome):
                    await outcome
            return view.shape(result)

        return run
