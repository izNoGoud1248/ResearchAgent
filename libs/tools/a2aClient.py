from typing import Any

import httpx
from a2a.client import A2AClientError, ClientConfig, create_client
from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.types import Role, SendMessageRequest
from a2a.utils.errors import A2AError

from libs.guardrails.agentToken import AgentTokenIssuer
from libs.telemetry.tracer import Tracer


class A2aCallError(Exception):
    pass


class A2aClient:
    """Calls another agent over A2A. The agent card is read from the peer's well-known URL."""

    def __init__(self, url: str, issuer: AgentTokenIssuer, audience: str, timeout: float = 180.0):
        self.url = url
        self.issuer = issuer
        self.audience = audience
        self.timeout = timeout

    async def ask(self, data: dict[str, Any], runId: str, traceId: str) -> dict[str, Any]:
        with Tracer.span(f"a2a.{self.audience}", runId=runId, **{"a2a.peer": self.url}):
            return await self.send(data, runId, traceId)

    async def send(self, data: dict[str, Any], runId: str, traceId: str) -> dict[str, Any]:
        token = self.issuer.issue("orchestrator", runId, traceId, audience=self.audience)
        headers = Tracer.inject({"Authorization": f"Bearer {token}"})
        async with httpx.AsyncClient(headers=headers, timeout=self.timeout) as http:
            client = await create_client(self.url, ClientConfig(httpx_client=http, streaming=False))
            try:
                request = SendMessageRequest(message=new_data_message(data, role=Role.ROLE_USER))
                async for response in client.send_message(request):
                    if response.HasField("message"):
                        return get_data_parts(response.message.parts)[0]
            except (A2AError, A2AClientError) as error:
                raise A2aCallError(f"{self.url} refused the request: {error}") from None
            finally:
                await client.close()
        raise A2aCallError(f"{self.url} answered without a message")
