import asyncio
import socket
import tempfile
import time
from pathlib import Path

from redis.asyncio import Redis


class Heartbeat:
    """Proves a worker's event loop is alive: a file for Kubernetes' liveness probe, and a Redis key that expires.

    If the loop hangs, both go stale: the probe restarts the pod and the worker drops off the live count.
    """

    keyPrefix = "worker:alive:"

    fileName = "researchdesk-heartbeat"

    def __init__(self, redis: Redis, path: Path | None = None, interval: float = 10.0):
        self.redis = redis
        # /tmp/researchdesk-heartbeat in the container, where the liveness probe reads it.
        self.path = path or Path(tempfile.gettempdir()) / self.fileName
        self.interval = interval
        self.name = socket.gethostname()

    async def run(self) -> None:
        while True:
            self.path.write_text(str(time.time()))
            await self.redis.set(f"{self.keyPrefix}{self.name}", int(time.time()), ex=max(1, round(self.interval * 3)))
            await asyncio.sleep(self.interval)

    async def stop(self) -> None:
        await self.redis.delete(f"{self.keyPrefix}{self.name}")

    @classmethod
    async def liveWorkers(cls, redis: Redis) -> int:
        return sum([1 async for _ in redis.scan_iter(match=f"{cls.keyPrefix}*")])
