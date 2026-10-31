import asyncio
import random
from collections.abc import Awaitable, Callable


class Retrier:
    def __init__(
        self,
        attempts: int = 3,
        baseDelay: float = 0.5,
        maxDelay: float = 8.0,
        timeout: float = 30.0,
        retryOn: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError),
    ):
        self.attempts = attempts
        self.baseDelay = baseDelay
        self.maxDelay = maxDelay
        self.timeout = timeout
        self.retryOn = retryOn

    async def run[T](self, action: Callable[[], Awaitable[T]]) -> T:
        attempt = 1
        while True:
            try:
                return await asyncio.wait_for(action(), self.timeout)
            except self.retryOn:
                if attempt >= self.attempts:
                    raise
                await asyncio.sleep(self.delayFor(attempt))
                attempt += 1

    def delayFor(self, attempt: int) -> float:
        # Full jitter keeps many clients from retrying in lockstep.
        return random.uniform(0, min(self.maxDelay, self.baseDelay * 2**attempt))
