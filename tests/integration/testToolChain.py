import os
import uuid

import pytest
from mcp import Client

from libs.guardrails.agentToken import AgentTokenIssuer
from libs.tools.gatewayClient import GatewayClient, ToolCallError
from tests.integration.conftest import RunningServer, ToolStack, ToolStackBuilder


def newRun() -> str:
    return f"test-{uuid.uuid4().hex[:12]}"


class TestToolChain:
    async def testResearcherSearchesArxivThroughGateway(self, toolStack: ToolStack):
        runId = newRun()
        result = await toolStack.client.call("researcher", runId, "trace1", "arxiv.search", {"query": "prompt injection defense", "maxResults": 3})
        assert 1 <= len(result["papers"]) <= 3
        assert all(paper["id"] and paper["title"] for paper in result["papers"])

        audit = await toolStack.audit.forRun(runId)
        assert [(row["agent"], row["tool"], row["outcome"], row["trace"]) for row in audit] == [("researcher", "arxiv.search", "allowed", "trace1")]

    async def testRepeatedSearchComesFromCache(self, toolStack: ToolStack, redis):
        arguments = {"query": "retrieval augmented generation evaluation", "maxResults": 2}
        first = await toolStack.client.call("researcher", newRun(), "trace1", "arxiv.search", arguments)
        second = await toolStack.client.call("researcher", newRun(), "trace1", "arxiv.search", arguments)
        assert first == second
        assert await redis.hget("cache:arxiv:stats", "hits") == "1"

    async def testResearcherMayNotSaveNotes(self, toolStack: ToolStack):
        runId = newRun()
        with pytest.raises(ToolCallError, match="may not call 'notes.save'"):
            await toolStack.client.call("researcher", runId, "trace1", "notes.save", {"title": "x", "body": "y"})
        audit = await toolStack.audit.forRun(runId)
        assert audit[0]["outcome"] == "denied"

    async def testWriterSavesNoteWithPiiRedactedAndRunIdFromToken(self, toolStack: ToolStack):
        runId = newRun()
        body = "Findings for the team. Contact jane.doe@example.com or +1 415-555-0132."
        saved = await toolStack.client.call("writer", runId, "trace1", "notes.save", {"title": "Report", "body": body})
        assert saved["runId"] == runId

        note = await toolStack.client.call("writer", runId, "trace1", "notes.read", {"noteId": saved["noteId"]})
        assert "jane.doe" not in note["body"]
        assert "[REDACTED:email]" in note["body"] and "[REDACTED:phone]" in note["body"]

        audit = await toolStack.audit.forRun(runId)
        assert audit[0]["pii"] == {"email": 1, "phone": 1}

    async def testUnknownNoteIsAFailedCallNotACrash(self, toolStack: ToolStack):
        runId = newRun()
        with pytest.raises(ToolCallError, match="not found"):
            await toolStack.client.call("writer", runId, "trace1", "notes.read", {"noteId": str(uuid.uuid4())})
        assert (await toolStack.audit.forRun(runId))[0]["outcome"] == "failed"

    async def testRejectsMissingToken(self, toolStack: ToolStack):
        async with Client(toolStack.url) as client:
            result = await client.call_tool("arxiv.search", {"query": "anything"})
        assert result.is_error
        assert "missing bearer token" in result.content[0].text

    async def testRejectsTokenFromUnknownKey(self, toolStack: ToolStack):
        forger = GatewayClient(toolStack.url, AgentTokenIssuer(os.urandom(32)))
        with pytest.raises(ToolCallError, match="invalid token"):
            await forger.call("writer", newRun(), "trace1", "notes.save", {"title": "x", "body": "y"})


class TestGatewayFailureModes:
    async def testRejectsResponseSignedWithWrongKey(self, stackBuilder: ToolStackBuilder):
        from services.mcpSearch.searchServer import SearchServer

        gateway = stackBuilder.gateway(searchKey=b"not-the-search-server-key")
        await gateway.audit.setup()
        search = SearchServer(stackBuilder.searchKey(), stackBuilder.redis)
        async with RunningServer(search.app("http://127.0.0.1"), stackBuilder.searchPort), RunningServer(gateway.app("http://127.0.0.1"), stackBuilder.gatewayPort):
            with pytest.raises(ToolCallError, match="signature does not match"):
                await stackBuilder.client().call("researcher", newRun(), "trace1", "arxiv.search", {"query": "llm agents", "maxResults": 1})

    async def testBreakerOpensWhenToolServerIsDown(self, stackBuilder: ToolStackBuilder):
        gateway = stackBuilder.gateway(searchUrl="http://127.0.0.1:8299/mcp")
        await gateway.audit.setup()
        client = stackBuilder.client()
        async with RunningServer(gateway.app("http://127.0.0.1"), stackBuilder.gatewayPort):
            for _ in range(3):
                with pytest.raises(ToolCallError, match="did not respond"):
                    await client.call("researcher", newRun(), "trace1", "arxiv.search", {"query": "x"})
            with pytest.raises(ToolCallError, match="circuit open"):
                await client.call("researcher", newRun(), "trace1", "arxiv.search", {"query": "x"})


class TestPaperLookup:
    @staticmethod
    def factCheckerClient(settings, url: str) -> GatewayClient:
        seed = settings.decodeKey(settings.factCheckerSigningSeed.get_secret_value())
        return GatewayClient(url, AgentTokenIssuer(seed, issuer="factChecker"))

    async def testFactCheckerFetchesCitedPapersAndSeesMissingOnes(self, toolStack: ToolStack, settings):
        client = self.factCheckerClient(settings, toolStack.url)
        result = await client.call(
            "factChecker", newRun(), "trace1", "arxiv.fetch", {"ids": ["1706.03762", "1512.03385v1", "2099.99999", "not-an-id"]}
        )
        titles = {paper["id"].split("v")[0]: paper["title"] for paper in result["papers"]}
        assert "Attention Is All You Need" in titles["1706.03762"]
        assert "Residual" in titles["1512.03385"]
        assert result["missing"] == ["2099.99999"]

    async def testWritersMayNotFetchById(self, toolStack: ToolStack):
        with pytest.raises(ToolCallError, match="may not call 'arxiv.fetch'"):
            await toolStack.client.call("writer", newRun(), "trace1", "arxiv.fetch", {"ids": ["1706.03762"]})


class TestSearchOptions:
    async def testNewestFirstAndSinceYear(self, toolStack: ToolStack):
        result = await toolStack.client.call(
            "researcher", newRun(), "trace1", "arxiv.search",
            {"query": "large language model agents", "maxResults": 5, "sortBy": "newest", "sinceYear": 2025},
        )
        dates = [paper["published"] for paper in result["papers"]]
        assert dates and all(date >= "2025-01-01" for date in dates)
        assert dates == sorted(dates, reverse=True)
