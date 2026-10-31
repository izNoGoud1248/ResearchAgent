import pytest

from libs.llm.costTracker import CostTracker
from libs.llm.modelRouter import ModelRouter


class TestModelRouter:
    router = ModelRouter("gpt-4o-mini", "gpt-4o")

    def testCheapByDefault(self):
        assert self.router.pick("planner", 500) == "gpt-4o-mini"

    def testStrongForWriterAndLongPrompts(self):
        assert self.router.pick("writer", 500) == "gpt-4o"
        assert self.router.pick("critic", 30000) == "gpt-4o"


class TestCostTracker:
    async def testPricesDatedModelNames(self, redis):
        tracker = CostTracker(redis)
        assert tracker.priceFor("gpt-4o-mini-2024-07-18", 1000000, 1000000) == pytest.approx(0.75)
        assert tracker.priceFor("gpt-4o-2024-08-06", 1000, 500) == pytest.approx(0.0075)
        with pytest.raises(KeyError):
            tracker.priceFor("unknown-model", 1, 1)

    async def testAddsUpPerRun(self, redis):
        tracker = CostTracker(redis)
        await tracker.record("run1", "gpt-4o-mini", 1000, 200)
        await tracker.record("run1", "gpt-4o", 1000, 200)
        await tracker.record("run2", "gpt-4o", 5, 5)
        total = await tracker.runTotal("run1")
        assert total["inputTokens"] == 2000
        assert total["outputTokens"] == 400
        assert total["usd"] == pytest.approx(0.00027 + 0.0045)
        assert total["calls:gpt-4o-mini"] == 1
        assert total["calls:gpt-4o"] == 1
