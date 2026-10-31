import asyncio
import time

from libs.reliability.heartbeat import Heartbeat


class TestHeartbeat:
    async def testBeatsThenExpiresWhenStopped(self, redis, tmp_path):
        heartbeat = Heartbeat(redis, path=tmp_path / "beat", interval=0.2)
        task = asyncio.create_task(heartbeat.run())
        await asyncio.sleep(0.3)
        assert await Heartbeat.liveWorkers(redis) == 1
        assert time.time() - float((tmp_path / "beat").read_text()) < 1

        task.cancel()
        await heartbeat.stop()
        assert await Heartbeat.liveWorkers(redis) == 0

    async def testFrozenWorkerDropsOffOnItsOwn(self, redis, tmp_path):
        heartbeat = Heartbeat(redis, path=tmp_path / "beat", interval=0.4)
        task = asyncio.create_task(heartbeat.run())
        await asyncio.sleep(0.1)
        task.cancel()  # stands in for a hung event loop: no more beats, no clean stop
        await asyncio.sleep(1.5)
        assert await Heartbeat.liveWorkers(redis) == 0
