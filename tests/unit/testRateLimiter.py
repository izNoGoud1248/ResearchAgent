import asyncio

from libs.reliability.rateLimiter import RateLimiter


class TestRateLimiter:
    async def testBucketEmptiesAndRefills(self, redis):
        limiter = RateLimiter(redis, "test", capacity=3, refillPerSecond=2)
        results = [await limiter.tryAcquire("userA") for _ in range(4)]
        assert [result.allowed for result in results] == [True, True, True, False]
        assert 0 < results[-1].retryAfter <= 0.5

        await asyncio.sleep(0.6)
        assert (await limiter.tryAcquire("userA")).allowed

    async def testSubjectsHaveSeparateBuckets(self, redis):
        limiter = RateLimiter(redis, "test", capacity=1, refillPerSecond=0.1)
        assert (await limiter.tryAcquire("userA")).allowed
        assert not (await limiter.tryAcquire("userA")).allowed
        assert (await limiter.tryAcquire("userB")).allowed

    async def testAcquireWaitsForToken(self, redis):
        limiter = RateLimiter(redis, "test", capacity=1, refillPerSecond=5)
        await limiter.acquire("userA")
        started = asyncio.get_running_loop().time()
        await limiter.acquire("userA")
        assert asyncio.get_running_loop().time() - started >= 0.15
