import asyncio

import pytest

from libs.reliability.jobQueue import JobQueue, QueueFullError


class TestJobQueue:
    async def testHighPriorityFirstThenFifo(self, redis):
        queue = JobQueue(redis, "test")
        await queue.push({"question": "a"}, "low")
        await queue.push({"question": "b"}, "normal")
        await queue.push({"question": "c"}, "normal")
        await queue.push({"question": "d"}, "high")

        order = [(await queue.pop()).payload["question"] for _ in range(4)]
        assert order == ["d", "b", "c", "a"]
        assert await queue.pop() is None

    async def testBackpressureRejectsWhenFull(self, redis):
        queue = JobQueue(redis, "test", maxDepth=2)
        await queue.push({"n": 1})
        await queue.push({"n": 2}, "high")
        with pytest.raises(QueueFullError):
            await queue.push({"n": 3})

    async def testAckRemovesLease(self, redis):
        queue = JobQueue(redis, "test")
        await queue.push({"n": 1})
        job = await queue.pop()
        assert (await queue.depth())["leased"] == 1
        await queue.ack(job)
        assert await queue.depth() == {"high": 0, "normal": 0, "low": 0, "leased": 0}

    async def testExpiredLeaseGoesBackToFrontOfQueue(self, redis):
        queue = JobQueue(redis, "test", leaseSeconds=1)
        await queue.push({"n": 1}, "low")
        await queue.push({"n": 2}, "low")
        crashed = await queue.pop()

        await asyncio.sleep(2.1)
        assert await queue.requeueExpired() == 1
        again = await queue.pop()
        assert again.id == crashed.id
        assert again.priority == "low"
