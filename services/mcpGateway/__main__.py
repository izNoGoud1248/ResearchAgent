from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from libs.guardrails.agentToken import AgentTokenVerifier
from libs.guardrails.permissionGuard import PermissionGuard
from libs.guardrails.responseValidator import ResponseValidator
from libs.serviceRunner import ServiceRunner
from libs.settings import Settings
from services.mcpGateway.auditLog import AuditLog
from services.mcpGateway.mcpGateway import McpGateway, Route


class GatewayService:
    async def start(self) -> None:
        settings = Settings()
        async with AsyncConnectionPool(settings.postgresUrl, open=False) as pool:
            audit = AuditLog(pool)
            await audit.setup()
            gateway = McpGateway(
                routes={
                    "arxiv.search": Route("mcpSearch", settings.searchUrl, "search"),
                    "arxiv.fetch": Route("mcpSearch", settings.searchUrl, "byId"),
                    "notes.save": Route("mcpNotes", settings.notesUrl, "save", passRunId=True),
                    "notes.read": Route("mcpNotes", settings.notesUrl, "read"),
                    "library.add": Route("mcpLibrary", settings.libraryUrl, "add", passRunId=True),
                    "library.search": Route("mcpLibrary", settings.libraryUrl, "search", passRunId=True, documents=True),
                    "paper.read": Route("mcpLibrary", settings.libraryUrl, "read", passRunId=True, documents=True),
                },
                verifier=AgentTokenVerifier(settings.trustedIssuers()),
                permissions=PermissionGuard.fromFile(Path(__file__).parent / "policy.yaml"),
                validator=ResponseValidator({
                    "mcpSearch": settings.searchHmacKey.get_secret_value().encode(),
                    "mcpNotes": settings.notesHmacKey.get_secret_value().encode(),
                    "mcpLibrary": settings.libraryHmacKey.get_secret_value().encode(),
                }),
                audit=audit,
                redis=settings.makeRedis(),
            )
            await ServiceRunner.serve(gateway.app(settings.gatewayUrl), settings.gatewayUrl)


if __name__ == "__main__":
    ServiceRunner.run("mcpGateway", GatewayService().start)
