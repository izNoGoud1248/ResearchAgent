import asyncio

import pytest

from libs.reliability.circuitBreaker import CircuitBreaker, CircuitOpenError


class FlakyService:
    def __init__(self):
        self.calls = 0
        self.healthy = False

    async def handle(self) -> str:
        self.calls += 1
        if not self.healthy:
            raise ConnectionError("service down")
        return "ok"


class TestCircuitBreaker:
    async def testOpensAfterLimitAndStopsCalling(self, redis):
        breaker = CircuitBreaker(redis, "test", failureLimit=3, coolDown=60)
        service = FlakyService()
        for _ in range(3):
            with pytest.raises(ConnectionError):
                await breaker.call(service.handle)
        assert await breaker.state() == "open"

        with pytest.raises(CircuitOpenError):
            await breaker.call(service.handle)
        assert service.calls == 3

    async def testStateIsSharedAcrossInstances(self, redis):
        first = CircuitBreaker(redis, "test", failureLimit=1, coolDown=60)
        with pytest.raises(ConnectionError):
            await first.call(FlakyService().handle)
        assert await CircuitBreaker(redis, "test").state() == "open"

    async def testHalfOpenProbeClosesOnSuccess(self, redis):
        breaker = CircuitBreaker(redis, "test", failureLimit=1, coolDown=0.5)
        service = FlakyService()
        with pytest.raises(ConnectionError):
            await breaker.call(service.handle)
        await asyncio.sleep(0.6)
        assert await breaker.state() == "halfOpen"

        service.healthy = True
        assert await breaker.call(service.handle) == "ok"
        assert await breaker.state() == "closed"

    async def testHalfOpenProbeReopensOnFailure(self, redis):
        breaker = CircuitBreaker(redis, "test", failureLimit=1, coolDown=0.5)
        service = FlakyService()
        with pytest.raises(ConnectionError):
            await breaker.call(service.handle)
        await asyncio.sleep(0.6)
        with pytest.raises(ConnectionError):
            await breaker.call(service.handle)
        assert await breaker.state() == "open"

    async def testIgnoresErrorsItDoesNotCount(self, redis):
        breaker = CircuitBreaker(redis, "test", failureLimit=1, countOn=(ConnectionError,))

        async def badRequest() -> str:
            raise ValueError("caller bug")

        with pytest.raises(ValueError):
            await breaker.call(badRequest)
        assert await breaker.state() == "closed"
