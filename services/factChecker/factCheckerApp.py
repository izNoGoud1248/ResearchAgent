from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from redis.asyncio import Redis
from starlette.applications import Starlette

from libs.guardrails.agentToken import AgentTokenIssuer, AgentTokenVerifier
from libs.llm.llmClient import LlmClient
from libs.settings import Settings
from libs.tools.gatewayClient import GatewayClient
from services.factChecker.factCheckerAgent import FactCheckerAgent


class FactCheckerApp:
    def __init__(self, settings: Settings, redis: Redis, gatewayUrl: str | None = None, publicUrl: str | None = None):
        agent = FactCheckerAgent(
            llm=LlmClient.fromSettings(settings, redis),
            tools=GatewayClient(
                gatewayUrl or settings.gatewayUrl,
                AgentTokenIssuer(settings.decodeKey(settings.factCheckerSigningSeed.get_secret_value()), issuer="factChecker"),
            ),
            verifier=AgentTokenVerifier({"orchestrator": settings.decodeKey(settings.agentPublicKey)}, audience="factChecker"),
        )
        card = FactCheckerAgent.card(publicUrl or settings.factCheckerUrl)
        handler = DefaultRequestHandler(agent_executor=agent, task_store=InMemoryTaskStore(), agent_card=card)
        self.app = Starlette(routes=[*create_agent_card_routes(card), *create_jsonrpc_routes(handler, "/")])
