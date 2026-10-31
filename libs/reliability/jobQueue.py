import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

from redis.asyncio import Redis


class QueueFullError(Exception):
    pass


@dataclass(frozen=True)
class Job:
    id: str
    priority: str
    payload: dict[str, Any]
    raw: str


class JobQueue:
    """One Redis list per priority (KEDA can watch list length), plus a lease set for jobs in progress."""

    priorities = ("high", "normal", "low")

    pushScript = """
local depth = 0
for i = 1, #KEYS do depth = depth + redis.call('LLEN', KEYS[i]) end
if depth >= tonumber(ARGV[1]) then return 0 end
redis.call('RPUSH', KEYS[tonumber(ARGV[2])], ARGV[3])
return 1
"""

    popScript = """
local clock = redis.call('TIME')
for i = 1, #KEYS - 1 do
  local item = redis.call('LPOP', KEYS[i])
  if item then
    redis.call('ZADD', KEYS[#KEYS], tonumber(clock[1]) + tonumber(ARGV[1]), item)
    return item
  end
end
return false
"""

    requeueScript = """
local clock = redis.call('TIME')
local expired = redis.call('ZRANGEBYSCORE', KEYS[4], '-inf', clock[1])
for _, item in ipairs(expired) do
  redis.call('ZREM', KEYS[4], item)
  local priority = cjson.decode(item).priority
  local target = KEYS[2]
  if priority == 'high' then target = KEYS[1] elseif priority == 'low' then target = KEYS[3] end
  redis.call('LPUSH', target, item)
end
return #expired
"""

    def __init__(self, redis: Redis, name: str, maxDepth: int = 100, leaseSeconds: int = 600):
        self.redis = redis
        self.listKeys = [f"queue:{name}:{priority}" for priority in self.priorities]
        self.leaseKey = f"queue:{name}:leased"
        self.maxDepth = maxDepth
        self.leaseSeconds = leaseSeconds
        self.pushJob = redis.register_script(self.pushScript)
        self.popJob = redis.register_script(self.popScript)
        self.requeueJobs = redis.register_script(self.requeueScript)

    async def push(self, payload: dict[str, Any], priority: str = "normal") -> str:
        jobId = uuid.uuid4().hex
        raw = json.dumps({"id": jobId, "priority": priority, "payload": payload})
        index = self.priorities.index(priority) + 1
        if not await self.pushJob(keys=self.listKeys, args=[self.maxDepth, index, raw]):
            raise QueueFullError(f"queue holds {self.maxDepth} jobs, try again later")
        return jobId

    async def pop(self) -> Job | None:
        raw = await self.popJob(keys=[*self.listKeys, self.leaseKey], args=[self.leaseSeconds])
        if raw is None:
            return None
        data = json.loads(raw)
        return Job(data["id"], data["priority"], data["payload"], raw)

    async def waitForJob(self, pollInterval: float = 0.5) -> Job:
        while True:
            job = await self.pop()
            if job:
                return job
            await asyncio.sleep(pollInterval)

    async def ack(self, job: Job) -> None:
        await self.redis.zrem(self.leaseKey, job.raw)

    async def requeueExpired(self) -> int:
        return await self.requeueJobs(keys=[*self.listKeys, self.leaseKey])

    async def depth(self) -> dict[str, int]:
        counts = [await self.redis.llen(key) for key in self.listKeys]
        return dict(zip(self.priorities, counts)) | {"leased": await self.redis.zcard(self.leaseKey)}
