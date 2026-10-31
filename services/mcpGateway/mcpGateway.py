import time
from dataclasses import asdict, dataclass
from typing import Any, Literal

import httpx2
import jwt
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult
from opentelemetry.trace import Span
from redis.asyncio import Redis
from starlette.applications import Starlette

from libs.guardrails.agentToken import AgentClaims, AgentTokenVerifier
from libs.guardrails.permissionGuard import PermissionGuard
from libs.guardrails.piiRedactor import PiiRedactor
from libs.guardrails.responseValidator import ResponseValidator
from libs.reliability.circuitBreaker import CircuitBreaker, CircuitOpenError
from libs.reliability.retrier import Retrier
from libs.telemetry.jsonLogger import JsonLogger
from libs.telemetry.tracer import Tracer
from libs.tools.mcpTransport import McpTransport
from services.mcpGateway.auditLog import AuditEntry, AuditLog


@dataclass(frozen=True)
class Route:
    server: str
    url: str
    tool: str
    passRunId: bool = False
    # Document text (papers) may quote attacks legitimately: neutralize instruction-like spans instead of rejecting.
    documents: bool = False


class GatewayRefusal(Exception):
    def __init__(self, reason: str, outcome: str = "denied"):
        super().__init__(reason)
        self.reason = reason
        self.outcome = outcome


class McpGateway:
    """Single entry point for agent tool calls: identity, permission, PII, signature and content checks, audit."""

    transientErrors = (httpx2.TransportError, TimeoutError, ConnectionError)

    def __init__(
        self,
        routes: dict[str, Route],
        verifier: AgentTokenVerifier,
        permissions: PermissionGuard,
        validator: ResponseValidator,
        audit: AuditLog,
        redis: Redis,
        retrier: Retrier | None = None,
    ):
        self.routes = routes
        self.verifier = verifier
        self.permissions = permissions
        self.validator = validator
        self.redactor = PiiRedactor()
        self.audit = audit
        self.log = JsonLogger("mcpGateway")
        self.retrier = retrier or Retrier(attempts=3, timeout=45, retryOn=self.transientErrors)
        self.breakers = {
            route.server: CircuitBreaker(redis, f"tool:{route.server}", failureLimit=3, coolDown=30, countOn=self.transientErrors)
            for route in routes.values()
        }
        self.server = MCPServer("mcpGateway")
        self.server.tool(name="arxiv.search", description="Search arXiv papers by keywords.")(self.arxivSearch)
        self.server.tool(name="arxiv.fetch", description="Look up arXiv papers by id.")(self.arxivFetch)
        self.server.tool(name="notes.save", description="Save the final report as a note.")(self.notesSave)
        self.server.tool(name="library.add", description="Add papers to the paper library.")(self.libraryAdd)
        self.server.tool(name="library.search", description="Search stored paper passages by meaning and keywords.")(self.librarySearch)
        self.server.tool(name="paper.read", description="Read a paper's full text by section.")(self.paperRead)
        self.server.tool(name="notes.read", description="Read a saved note by id.")(self.notesRead)

    def app(self, url: str) -> Starlette:
        return self.server.streamable_http_app(stateless_http=True, json_response=True, transport_security=McpTransport.security(url))

    async def arxivSearch(
        self,
        query: str,
        ctx: Context,
        maxResults: int = 5,
        sortBy: Literal["relevance", "newest"] = "relevance",
        sinceYear: int | None = None,
    ) -> dict[str, Any]:
        arguments = {"query": query, "maxResults": maxResults, "sortBy": sortBy}
        return await self.forward(ctx, "arxiv.search", arguments | ({"sinceYear": sinceYear} if sinceYear else {}))

    async def arxivFetch(self, ids: list[str], ctx: Context) -> dict[str, Any]:
        return await self.forward(ctx, "arxiv.fetch", {"ids": ids})

    async def libraryAdd(self, papers: list[dict[str, Any]], ctx: Context) -> dict[str, Any]:
        return await self.forward(ctx, "library.add", {"papers": papers})

    async def librarySearch(self, query: str, ctx: Context, limit: int = 6, paperIds: list[str] | None = None) -> dict[str, Any]:
        return await self.forward(ctx, "library.search", {"query": query, "limit": limit} | ({"paperIds": paperIds} if paperIds else {}))

    async def paperRead(self, paperId: str, ctx: Context, section: str | None = None) -> dict[str, Any]:
        return await self.forward(ctx, "paper.read", {"paperId": paperId} | ({"section": section} if section else {}))

    async def notesSave(self, title: str, body: str, ctx: Context) -> dict[str, Any]:
        return await self.forward(ctx, "notes.save", {"title": title, "body": body})

    async def notesRead(self, noteId: str, ctx: Context) -> dict[str, Any]:
        return await self.forward(ctx, "notes.read", {"noteId": noteId})

    async def forward(self, ctx: Context, toolName: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # A refusal is an expected outcome, recorded in the audit log and on the span, not a crash.
        with Tracer.span(f"gateway.{toolName}", carrier=ctx.headers or {}, expected=(ToolError,)) as span:
            return await self.checkedCall(ctx, toolName, arguments, span)

    async def checkedCall(self, ctx: Context, toolName: str, arguments: dict[str, Any], span: Span) -> dict[str, Any]:
        started = time.perf_counter()
        entry = AuditEntry(tool=toolName, outcome="allowed", ms=0)
        try:
            claims = self.identify(ctx)
            entry.agent, entry.issuer, entry.run, entry.trace = claims.agent, claims.issuer, claims.runId, claims.traceId

            verdict = self.permissions.checkCall(claims, toolName)
            if not verdict.allowed:
                raise GatewayRefusal(verdict.reason)

            route = self.routes[toolName]
            inbound = self.redactor.redact(arguments | ({"runId": claims.runId} if route.passRunId else {}))
            result = await self.callTool(route, inbound.value)

            body = result.structured_content or {}
            if route.documents:
                verdict = self.validator.verifySignature(route.server, body.get("payload"), body.get("signature", ""))
            else:
                verdict = self.validator.validate(route.server, body.get("payload"), body.get("signature", ""))
            if not verdict.allowed:
                raise GatewayRefusal(f"tool response rejected: {verdict.reason}")
            payload = body["payload"]
            if route.documents:
                payload, removed = self.validator.neutralize(payload)
                if removed:
                    entry.reason = f"neutralized {removed} instruction-like span(s) in document text"

            outbound = self.redactor.redact(payload)
            entry.pii = self.mergeCounts(inbound.found, outbound.found)
            return outbound.value
        except GatewayRefusal as refusal:
            entry.outcome, entry.reason = refusal.outcome, refusal.reason
            raise ToolError(refusal.reason) from None
        except Exception as error:
            entry.outcome, entry.reason = "failed", f"{type(error).__name__}: {error}"
            raise
        finally:
            entry.ms = int((time.perf_counter() - started) * 1000)
            span.set_attributes({"agent": entry.agent, "issuer": entry.issuer, "outcome": entry.outcome, "reason": entry.reason})
            await self.audit.record(entry)
            self.log.info(f"{toolName} {entry.outcome}", event="audit", **asdict(entry))

    def identify(self, ctx: Context) -> AgentClaims:
        headers = {name.lower(): value for name, value in (ctx.headers or {}).items()}
        authorization = headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            raise GatewayRefusal("missing bearer token")
        try:
            return self.verifier.verify(authorization.removeprefix("Bearer "))
        except jwt.InvalidTokenError as error:
            raise GatewayRefusal(f"invalid token: {error}") from None

    async def callTool(self, route: Route, arguments: dict[str, Any]) -> CallToolResult:
        try:
            result = await self.breakers[route.server].call(
                lambda: self.retrier.run(lambda: self.callDownstream(route, arguments))
            )
        except CircuitOpenError:
            raise GatewayRefusal(f"{route.server} is unavailable (circuit open)", "failed") from None
        except self.transientErrors as error:
            raise GatewayRefusal(f"{route.server} did not respond: {type(error).__name__}", "failed") from None
        if result.is_error:
            raise GatewayRefusal(self.errorText(result), "failed")
        return result

    async def callDownstream(self, route: Route, arguments: dict[str, Any]) -> CallToolResult:
        # The MCP client runs inside a task group, so network errors arrive wrapped in an ExceptionGroup.
        try:
            # Searches can wait several seconds on the arXiv rate limit, so reads get far longer than httpx's 5s default.
            async with httpx2.AsyncClient(headers=Tracer.inject(), timeout=httpx2.Timeout(30, read=120)) as http:
                async with Client(streamable_http_client(route.url, http_client=http)) as client:
                    return await client.call_tool(route.tool, arguments)
        except* self.transientErrors as group:
            error: BaseException = group
            while isinstance(error, BaseExceptionGroup):
                error = error.exceptions[0]
            raise error from None

    @staticmethod
    def errorText(result: CallToolResult) -> str:
        return " ".join(getattr(block, "text", "") for block in result.content) or "tool failed"

    @staticmethod
    def mergeCounts(first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
        return {kind: first.get(kind, 0) + second.get(kind, 0) for kind in first.keys() | second.keys()}
