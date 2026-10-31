import time
from collections.abc import Awaitable, Callable

from redis.asyncio import Redis


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    """Shared across replicas through Redis. States: closed, open, halfOpen (one probe at a time)."""

    def __init__(
        self,
        redis: Redis,
        name: str,
        failureLimit: int = 5,
        coolDown: float = 30.0,
        countOn: tuple[type[BaseException], ...] = (Exception,),
    ):
        self.redis = redis
        self.name = name
        self.key = f"breaker:{name}"
        self.probeKey = f"breaker:{name}:probe"
        self.failureLimit = failureLimit
        self.coolDown = coolDown
        self.countOn = countOn

    async def state(self) -> str:
        data = await self.redis.hgetall(self.key)
        state = data.get("state", "closed")
        if state == "open" and time.time() - float(data["openedAt"]) >= self.coolDown:
            return "halfOpen"
        return state

    async def call[T](self, action: Callable[[], Awaitable[T]]) -> T:
        state = await self.state()
        if state == "open":
            raise CircuitOpenError(self.name)
        if state == "halfOpen" and not await self.redis.set(self.probeKey, "1", nx=True, px=int(self.coolDown * 1000)):
            raise CircuitOpenError(self.name)
        try:
            result = await action()
        except self.countOn:
            await self.recordFailure(state)
            raise
        await self.recordSuccess()
        return result

    async def recordFailure(self, state: str) -> None:
        failures = await self.redis.hincrby(self.key, "failures", 1)
        if state == "halfOpen" or failures >= self.failureLimit:
            await self.redis.hset(self.key, mapping={"state": "open", "openedAt": time.time(), "failures": 0})
        await self.redis.delete(self.probeKey)

    async def recordSuccess(self) -> None:
        await self.redis.delete(self.key, self.probeKey)
