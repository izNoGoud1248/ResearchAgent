import pytest

from libs.llm.llmClient import LlmClient
from libs.settings import Settings

pytestmark = pytest.mark.llm


class TestLlmClient:
    async def testRealCompletionIsTrackedAndCached(self, settings: Settings, redis):
        if settings.openaiApiKey is None:
            pytest.skip("OPENAI_API_KEY is not set in .env")
        client = LlmClient.fromSettings(settings, redis)
        messages = [{"role": "user", "content": "Reply with exactly one word: ready"}]

        first = await client.complete("planner", messages, runId="testRun")
        assert "ready" in first.text.lower()
        assert first.model.startswith(settings.cheapModel)
        assert first.cost > 0 and not first.cached

        second = await client.complete("planner", messages, runId="testRun")
        assert second.cached and second.text == first.text and second.cost == 0

        total = await client.costTracker.runTotal("testRun")
        assert total["usd"] == pytest.approx(first.cost)
        print(f"\nOpenAI cost for this test: ${total['usd']:.6f}")

    async def testJsonMode(self, settings: Settings, redis):
        if settings.openaiApiKey is None:
            pytest.skip("OPENAI_API_KEY is not set in .env")
        client = LlmClient.fromSettings(settings, redis)
        messages = [
            {"role": "system", "content": "Answer in JSON."},
            {"role": "user", "content": 'Return {"subQuestions": [...]} with two sub-questions about RAG evaluation.'},
        ]
        reply = await client.complete("planner", messages, runId="testRun", jsonMode=True)
        assert reply.text.strip().startswith("{")
        assert "subQuestions" in reply.text
