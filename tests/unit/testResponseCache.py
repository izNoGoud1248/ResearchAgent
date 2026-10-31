import asyncio

from libs.llm.responseCache import ResponseCache


class Counter:
    def __init__(self):
        self.calls = 0

    async def compute(self) -> dict[str, int]:
        self.calls += 1
        return {"value": self.calls}


class TestResponseCache:
    async def testComputesOnceThenHits(self, redis):
        cache = ResponseCache(redis, "test")
        counter = Counter()
        first, firstHit = await cache.getOrCompute({"q": "x"}, counter.compute)
        second, secondHit = await cache.getOrCompute({"q": "x"}, counter.compute)
        assert (first, firstHit, second, secondHit) == ({"value": 1}, False, {"value": 1}, True)
        assert await cache.stats() == {"hits": 1, "misses": 1, "hitRate": 0.5}

    async def testKeyIgnoresDictOrder(self, redis):
        cache = ResponseCache(redis, "test")
        await cache.set({"a": 1, "b": 2}, "stored")
        assert await cache.get({"b": 2, "a": 1}) == "stored"

    async def testEvictsLeastRecentlyUsed(self, redis):
        cache = ResponseCache(redis, "test", maxEntries=2)
        await cache.set("first", 1)
        await cache.set("second", 2)
        await cache.get("first")
        await cache.set("third", 3)
        assert await cache.get("second") is None
        assert await cache.get("first") == 1
        assert await cache.get("third") == 3

    async def testEntriesExpire(self, redis):
        cache = ResponseCache(redis, "test", ttl=1)
        await cache.set("short", "lived")
        await asyncio.sleep(1.2)
        assert await cache.get("short") is None
