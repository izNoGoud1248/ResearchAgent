from typing import Any

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from libs.guardrails.agentToken import AgentTokenIssuer
from libs.telemetry.tracer import Tracer


class ToolCallError(Exception):
    pass


class GatewayClient:
    """How agents call tools. Each call carries a fresh short-lived token naming the agent, run and trace."""

    def __init__(self, url: str, issuer: AgentTokenIssuer, timeout: float = 120.0):
        self.url = url
        self.issuer = issuer
        self.timeout = timeout

    async def listTools(self, agent: str, runId: str, traceId: str) -> list[dict[str, Any]]:
        """What the gateway offers. Listing is open; calling is still checked per agent at the gateway."""
        headers = Tracer.inject({"Authorization": f"Bearer {self.issuer.issue(agent, runId, traceId)}"})
        async with httpx2.AsyncClient(headers=headers, timeout=self.timeout) as http:
            async with Client(streamable_http_client(self.url, http_client=http)) as client:
                listed = await client.list_tools()
        return [{"name": tool.name, "description": tool.description or "", "inputSchema": tool.input_schema} for tool in listed.tools]

    async def call(self, agent: str, runId: str, traceId: str, tool: str, arguments: dict[str, Any]) -> Any:
        with Tracer.span(f"tool.{tool}", agent=agent, runId=runId) as span:
            token = self.issuer.issue(agent, runId, traceId)
            headers = Tracer.inject({"Authorization": f"Bearer {token}"})
            async with httpx2.AsyncClient(headers=headers, timeout=self.timeout) as http:
                async with Client(streamable_http_client(self.url, http_client=http)) as client:
                    result = await client.call_tool(tool, arguments)
            if result.is_error:
                message = " ".join(getattr(block, "text", "") for block in result.content)
                span.set_attribute("tool.refused", message[:300])
                raise ToolCallError(message)
            return result.structured_content
