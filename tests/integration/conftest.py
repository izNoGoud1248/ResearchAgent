import asyncio
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import uvicorn
from starlette.types import ASGIApp

from libs.guardrails.agentToken import AgentTokenIssuer, AgentTokenVerifier
from libs.guardrails.permissionGuard import PermissionGuard
from libs.guardrails.responseValidator import ResponseValidator
from libs.llm.llmClient import LlmClient
from libs.reliability.jobQueue import JobQueue
from libs.reliability.rateLimiter import RateLimiter
from libs.reliability.retrier import Retrier
from libs.runEvents import RunEvents
from libs.settings import Settings
from libs.tools.gatewayClient import GatewayClient
from services.api.apiApp import ApiApp
from services.mcpGateway.auditLog import AuditLog
from services.mcpGateway.mcpGateway import McpGateway, Route
from services.mcpLibrary.fullTextReader import FullTextReader
from services.mcpLibrary.libraryServer import LibraryServer
from services.mcpNotes.notesServer import NotesServer
from services.mcpSearch.searchServer import SearchServer
from services.orchestrator.orchestratorFactory import OrchestratorFactory
from services.orchestrator.runStore import RunStore

projectRoot = Path(__file__).resolve().parents[2]


class RunningServer:
    def __init__(self, app: ASGIApp, port: int):
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    async def __aenter__(self) -> "RunningServer":
        self.task = asyncio.create_task(self.server.serve())
        while not self.server.started:
            if self.task.done():
                self.task.result()
            await asyncio.sleep(0.05)
        return self

    async def __aexit__(self, *details: object) -> None:
        self.server.should_exit = True
        await self.task


@dataclass
class ToolStack:
    gateway: McpGateway
    client: GatewayClient
    audit: AuditLog
    url: str


class ToolStackBuilder:
    searchPort, notesPort, gatewayPort, libraryPort = 8201, 8202, 8203, 8205

    def __init__(self, settings: Settings, redis, pool):
        self.settings = settings
        self.redis = redis
        self.pool = pool

    def searchKey(self) -> bytes:
        return self.settings.searchHmacKey.get_secret_value().encode()

    def libraryKey(self) -> bytes:
        return self.settings.libraryHmacKey.get_secret_value().encode()

    def notesKey(self) -> bytes:
        return self.settings.notesHmacKey.get_secret_value().encode()

    def gateway(self, searchUrl: str | None = None, searchKey: bytes | None = None) -> McpGateway:
        notesUrl = f"http://127.0.0.1:{self.notesPort}/mcp"
        libraryUrl = f"http://127.0.0.1:{self.libraryPort}/mcp"
        return McpGateway(
            routes={
                "arxiv.search": Route("mcpSearch", searchUrl or f"http://127.0.0.1:{self.searchPort}/mcp", "search"),
                "arxiv.fetch": Route("mcpSearch", searchUrl or f"http://127.0.0.1:{self.searchPort}/mcp", "byId"),
                "notes.save": Route("mcpNotes", notesUrl, "save", passRunId=True),
                "notes.read": Route("mcpNotes", notesUrl, "read"),
                "library.add": Route("mcpLibrary", libraryUrl, "add", passRunId=True),
                "library.search": Route("mcpLibrary", libraryUrl, "search", passRunId=True, documents=True),
                "paper.read": Route("mcpLibrary", libraryUrl, "read", passRunId=True, documents=True),
            },
            verifier=AgentTokenVerifier(self.settings.trustedIssuers()),
            permissions=PermissionGuard.fromFile(projectRoot / "services" / "mcpGateway" / "policy.yaml"),
            validator=ResponseValidator({
                "mcpSearch": searchKey or self.searchKey(), "mcpNotes": self.notesKey(), "mcpLibrary": self.libraryKey(),
            }),
            audit=AuditLog(self.pool),
            redis=self.redis,
            retrier=Retrier(attempts=2, baseDelay=0.05, timeout=45, retryOn=McpGateway.transientErrors),
        )

    def client(self) -> GatewayClient:
        issuer = AgentTokenIssuer(Settings.decodeKey(self.settings.agentSigningSeed.get_secret_value()))
        return GatewayClient(f"http://127.0.0.1:{self.gatewayPort}/mcp", issuer)


class ApiHarness:
    def __init__(self, settings: Settings, redis, pool, maxDepth: int = 50, askPerMinute: int = 10):
        self.runs = RunStore(pool)
        self.queue = JobQueue(redis, OrchestratorFactory.queueName, maxDepth=maxDepth)
        self.events = RunEvents(redis)
        self.audit = AuditLog(pool)
        self.api = ApiApp(settings, redis, self.runs, self.queue, self.audit, askPerMinute=askPerMinute)
        self.userHeaders = {"X-Api-Key": settings.userApiKey.get_secret_value()}
        self.approverHeaders = {"X-Api-Key": settings.approverApiKey.get_secret_value()}

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.api.app), base_url="http://api", timeout=60)


@pytest.fixture
def stackBuilder(settings: Settings, redis, pool) -> ToolStackBuilder:
    return ToolStackBuilder(settings, redis, pool)


@pytest.fixture
async def toolStack(stackBuilder: ToolStackBuilder):
    notes = NotesServer(stackBuilder.notesKey(), stackBuilder.pool)
    await notes.setup()
    gateway = stackBuilder.gateway()
    await gateway.audit.setup()
    search = SearchServer(stackBuilder.searchKey(), stackBuilder.redis)
    library = LibraryServer(
        stackBuilder.libraryKey(),
        stackBuilder.pool,
        LlmClient.fromSettings(stackBuilder.settings, stackBuilder.redis),
        FullTextReader(RateLimiter(stackBuilder.redis, "arxiv", capacity=1, refillPerSecond=1 / 3)),
    )
    await library.setup()
    async with (
        RunningServer(search.app("http://127.0.0.1"), stackBuilder.searchPort),
        RunningServer(notes.app("http://127.0.0.1"), stackBuilder.notesPort),
        RunningServer(library.app("http://127.0.0.1"), stackBuilder.libraryPort),
        RunningServer(gateway.app("http://127.0.0.1"), stackBuilder.gatewayPort),
    ):
        yield ToolStack(gateway, stackBuilder.client(), gateway.audit, f"http://127.0.0.1:{stackBuilder.gatewayPort}/mcp")
