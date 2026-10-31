from psycopg_pool import AsyncConnectionPool

from libs.guardrails.agentToken import AgentTokenIssuer
from libs.llm.llmClient import LlmClient
from libs.serviceRunner import ServiceRunner
from libs.settings import Settings
from libs.tools.gatewayClient import GatewayClient
from services.api.apiApp import ApiApp
from services.api.followUpAnswerer import FollowUpAnswerer
from services.mcpGateway.auditLog import AuditLog
from services.orchestrator.orchestratorFactory import OrchestratorFactory
from services.orchestrator.runStore import RunStore


class ApiService:
    async def start(self) -> None:
        settings = Settings()
        redis = settings.makeRedis()
        async with AsyncConnectionPool(settings.postgresUrl, open=False) as pool:
            runs = RunStore(pool)
            await runs.setup()
            audit = AuditLog(pool)
            await audit.setup()
            issuer = AgentTokenIssuer(settings.decodeKey(settings.agentSigningSeed.get_secret_value()))
            followUp = FollowUpAnswerer(LlmClient.fromSettings(settings, redis), GatewayClient(settings.gatewayUrl, issuer))
            api = ApiApp(settings, redis, runs, OrchestratorFactory.queue(redis), audit, followUp=followUp)
            await ServiceRunner.serve(api.app, settings.apiUrl)


if __name__ == "__main__":
    ServiceRunner.run("api", ApiService().start)
