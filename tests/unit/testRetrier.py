import asyncio

import pytest

from libs.reliability.retrier import Retrier


class UnstableAction:
    def __init__(self, failuresBeforeSuccess: int, slow: bool = False):
        self.failuresLeft = failuresBeforeSuccess
        self.slow = slow
        self.calls = 0

    async def run(self) -> str:
        self.calls += 1
        if self.failuresLeft > 0:
            self.failuresLeft -= 1
            if self.slow:
                await asyncio.sleep(1)
            raise ConnectionError("temporary")
        return "done"


class TestRetrier:
    retrier = Retrier(attempts=3, baseDelay=0.01, maxDelay=0.05, timeout=0.2)

    async def testSucceedsAfterTransientFailures(self):
        action = UnstableAction(failuresBeforeSuccess=2)
        assert await self.retrier.run(action.run) == "done"
        assert action.calls == 3

    async def testGivesUpAfterLastAttempt(self):
        action = UnstableAction(failuresBeforeSuccess=5)
        with pytest.raises(ConnectionError):
            await self.retrier.run(action.run)
        assert action.calls == 3

    async def testTimeoutCountsAsRetryableFailure(self):
        action = UnstableAction(failuresBeforeSuccess=1, slow=True)
        assert await self.retrier.run(action.run) == "done"
        assert action.calls == 2

    async def testDoesNotRetryOtherErrors(self):
        calls = 0

        async def broken() -> str:
            nonlocal calls
            calls += 1
            raise ValueError("bug")

        with pytest.raises(ValueError):
            await self.retrier.run(broken)
        assert calls == 1
