import asyncio
from dataclasses import dataclass

from redis.asyncio import Redis


@dataclass(frozen=True)
class Acquire:
    allowed: bool
    retryAfter: float


class RateLimiter:
    # Token bucket kept in one Redis hash. Uses the Redis clock so every replica agrees on time.
    bucketScript = """
local capacity = tonumber(ARGV[1])
local rate = tonumber(ARGV[2])
local cost = tonumber(ARGV[3])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000

local state = redis.call('HMGET', KEYS[1], 'tokens', 'stamp')
local tokens = tonumber(state[1]) or capacity
local stamp = tonumber(state[2]) or now
tokens = math.min(capacity, tokens + (now - stamp) * rate)

local allowed = 0
local wait = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  wait = (cost - tokens) / rate
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'stamp', now)
redis.call('PEXPIRE', KEYS[1], math.ceil(capacity / rate * 1000) + 1000)
return {allowed, tostring(wait)}
"""

    def __init__(self, redis: Redis, name: str, capacity: int, refillPerSecond: float):
        self.key = f"rate:{name}"
        self.capacity = capacity
        self.refillPerSecond = refillPerSecond
        self.bucket = redis.register_script(self.bucketScript)

    async def tryAcquire(self, subject: str, cost: int = 1) -> Acquire:
        allowed, wait = await self.bucket(
            keys=[f"{self.key}:{subject}"],
            args=[self.capacity, self.refillPerSecond, cost],
        )
        return Acquire(int(allowed) == 1, float(wait))

    async def acquire(self, subject: str, cost: int = 1) -> None:
        while True:
            result = await self.tryAcquire(subject, cost)
            if result.allowed:
                return
            await asyncio.sleep(result.retryAfter)
