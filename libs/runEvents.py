import json
from typing import Any

from redis.asyncio import Redis


class RunEvents:
    """Live events per run in a Redis Stream. Stream ids double as SSE ids, so clients can resume."""

    finalKinds = ("runFinished", "runFailed")

    def __init__(self, redis: Redis, keepSeconds: int = 86400, maxLength: int = 2000):
        self.redis = redis
        self.keepSeconds = keepSeconds
        self.maxLength = maxLength

    @staticmethod
    def key(runId: str) -> str:
        return f"run:{runId}:events"

    async def publish(self, runId: str, kind: str, **data: Any) -> str:
        key = self.key(runId)
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.xadd(key, {"kind": kind, "data": json.dumps(data, default=str)}, maxlen=self.maxLength, approximate=True)
            pipe.expire(key, self.keepSeconds)
            eventId, _ = await pipe.execute()
        return eventId

    async def read(self, runId: str, afterId: str = "0", blockMs: int = 15000) -> list[dict[str, Any]]:
        response = await self.redis.xread({self.key(runId): afterId}, block=blockMs, count=100)
        if not response:
            return []
        _, entries = response[0]
        return [{"id": eventId, "kind": fields["kind"], "data": json.loads(fields["data"])} for eventId, fields in entries]
