import asyncio
import re
from typing import Any, Literal

import arxiv
from mcp.server.mcpserver import Context, MCPServer
from redis.asyncio import Redis
from starlette.applications import Starlette

from libs.guardrails.responseValidator import ResponseSigner
from libs.llm.responseCache import ResponseCache
from libs.reliability.rateLimiter import RateLimiter
from libs.reliability.retrier import Retrier
from libs.telemetry.tracer import Tracer
from libs.tools.mcpTransport import McpTransport


class SearchServer:
    idPattern = re.compile(r"\d{4}\.\d{4,5}(v\d+)?")

    def __init__(self, hmacKey: bytes, redis: Redis):
        self.signer = ResponseSigner(hmacKey)
        # Pacing is done by our Redis limiter so it holds across replicas; arXiv asks for one call every 3 seconds.
        self.arxiv = arxiv.Client(page_size=10, delay_seconds=0, num_retries=0)
        self.limiter = RateLimiter(redis, "arxiv", capacity=1, refillPerSecond=1 / 3)
        self.cache = ResponseCache(redis, "arxiv", ttl=21600)
        self.retrier = Retrier(
            attempts=3,
            timeout=30,
            retryOn=(arxiv.HTTPError, arxiv.UnexpectedEmptyPageError, TimeoutError, ConnectionError),
        )
        self.server = MCPServer("mcpSearch")
        self.server.tool(
            name="search",
            description="Search arXiv by keywords. Returns id, title, authors, date, summary and link per paper.",
        )(self.search)
        self.server.tool(
            name="byId",
            description="Look up arXiv papers by id, for example 2403.04957 or 2403.04957v1. Unknown ids are listed as missing.",
        )(self.byId)

    def app(self, url: str) -> Starlette:
        return self.server.streamable_http_app(stateless_http=True, json_response=True, transport_security=McpTransport.security(url))

    async def search(
        self,
        query: str,
        ctx: Context,
        maxResults: int = 5,
        sortBy: Literal["relevance", "newest"] = "relevance",
        sinceYear: int | None = None,
    ) -> dict[str, Any]:
        """Keyword search. sortBy newest and sinceYear make "latest work" questions return recent papers."""
        maxResults = max(1, min(maxResults, 10))
        fullQuery = f"({query}) AND submittedDate:[{sinceYear}01010000 TO 299912312359]" if sinceYear else query
        order = arxiv.SortCriterion.SubmittedDate if sortBy == "newest" else arxiv.SortCriterion.Relevance
        with Tracer.span("mcpSearch.search", carrier=ctx.headers or {}, query=query, sortBy=sortBy) as span:
            papers, cached = await self.cache.getOrCompute(
                {"query": fullQuery, "maxResults": maxResults, "sortBy": sortBy},
                lambda: self.retrier.run(lambda: self.fetch(arxiv.Search(query=fullQuery, max_results=maxResults, sort_by=order))),
            )
            span.set_attributes({"cached": cached, "papers": len(papers)})
        payload = {"query": query, "papers": papers}
        return {"payload": payload, "signature": self.signer.sign(payload)}

    async def byId(self, ids: list[str], ctx: Context) -> dict[str, Any]:
        # Ids come from model-written text, so only well-formed modern arXiv ids are passed on, at most 20.
        wanted = sorted({paperId.strip() for paperId in ids if self.idPattern.fullmatch(paperId.strip())})[:20]
        with Tracer.span("mcpSearch.byId", carrier=ctx.headers or {}, requested=len(ids)) as span:
            papers, cached = (
                await self.cache.getOrCompute(
                    {"ids": wanted},
                    lambda: self.retrier.run(lambda: self.fetch(arxiv.Search(id_list=wanted, max_results=len(wanted)))),
                )
                if wanted
                else ([], False)
            )
            span.set_attributes({"cached": cached, "papers": len(papers)})
        found = {paper["id"].split("v")[0] for paper in papers}
        missing = [paperId for paperId in wanted if paperId.split("v")[0] not in found]
        payload = {"papers": papers, "missing": missing}
        return {"payload": payload, "signature": self.signer.sign(payload)}

    async def fetch(self, search: arxiv.Search) -> list[dict[str, Any]]:
        with Tracer.span("arxiv.api"):
            await self.limiter.acquire("global")
            return await asyncio.to_thread(self.fetchBlocking, search)

    def fetchBlocking(self, search: arxiv.Search) -> list[dict[str, Any]]:
        return [self.describe(result) for result in self.arxiv.results(search)]

    @staticmethod
    def describe(result: arxiv.Result) -> dict[str, Any]:
        return {
            "id": result.get_short_id(),
            "title": " ".join(result.title.split()),
            "authors": [author.name for author in result.authors[:5]],
            "published": result.published.date().isoformat(),
            "summary": " ".join(result.summary.split())[:1500],
            "url": result.entry_id,
        }
