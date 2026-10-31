import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis


class ResponseCache:
    """TTL per entry plus an LRU cap per namespace. Redis runs with noeviction, so the cap lives here."""

    def __init__(self, redis: Redis, namespace: str, ttl: int = 3600, maxEntries: int = 1000):
        self.redis = redis
        self.prefix = f"cache:{namespace}"
        self.indexKey = f"{self.prefix}:recent"
        self.statsKey = f"{self.prefix}:stats"
        self.ttl = ttl
        self.maxEntries = maxEntries

    @staticmethod
    def keyFor(request: Any) -> str:
        return hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()

    async def get(self, request: Any) -> Any | None:
        key = self.keyFor(request)
        raw = await self.redis.get(f"{self.prefix}:{key}")
        async with self.redis.pipeline(transaction=False) as pipe:
            if raw is None:
                pipe.hincrby(self.statsKey, "misses", 1)
            else:
                pipe.hincrby(self.statsKey, "hits", 1)
                pipe.zadd(self.indexKey, {key: time.time() * 1000000})
            await pipe.execute()
        return None if raw is None else json.loads(raw)

    async def set(self, request: Any, value: Any) -> None:
        key = self.keyFor(request)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.set(f"{self.prefix}:{key}", json.dumps(value), ex=self.ttl)
            pipe.zadd(self.indexKey, {key: time.time() * 1000000})
            pipe.zcard(self.indexKey)
            size = (await pipe.execute())[-1]
        if size > self.maxEntries:
            evicted = await self.redis.zpopmin(self.indexKey, size - self.maxEntries)
            await self.redis.delete(*[f"{self.prefix}:{key}" for key, _ in evicted])

    async def getOrCompute(self, request: Any, compute: Callable[[], Awaitable[Any]]) -> tuple[Any, bool]:
        cached = await self.get(request)
        if cached is not None:
            return cached, True
        value = await compute()
        await self.set(request, value)
        return value, False

    async def stats(self) -> dict[str, float]:
        data = await self.redis.hgetall(self.statsKey)
        hits, misses = int(data.get("hits", 0)), int(data.get("misses", 0))
        return {"hits": hits, "misses": misses, "hitRate": hits / (hits + misses) if hits + misses else 0.0}
