from redis.asyncio import Redis


class CostTracker:
    # USD per million tokens (input, output). Update when OpenAI changes pricing.
    pricesPerMillion = {
        "gpt-4o-mini": (0.15, 0.60),
        "gpt-4o": (2.50, 10.00),
        "text-embedding-3-small": (0.02, 0.0),
    }

    def __init__(self, redis: Redis, keepDays: int = 30):
        self.redis = redis
        self.keepSeconds = keepDays * 86400

    def priceFor(self, model: str, inputTokens: int, outputTokens: int) -> float:
        # API replies use dated names like gpt-4o-mini-2024-07-18, so match the longest known prefix.
        for name in sorted(self.pricesPerMillion, key=len, reverse=True):
            if model.startswith(name):
                inputPrice, outputPrice = self.pricesPerMillion[name]
                return (inputTokens * inputPrice + outputTokens * outputPrice) / 1000000
        raise KeyError(f"no price for model {model!r}")

    async def record(self, runId: str, model: str, inputTokens: int, outputTokens: int) -> float:
        cost = self.priceFor(model, inputTokens, outputTokens)
        runKey = f"cost:run:{runId}"
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.hincrby(runKey, "inputTokens", inputTokens)
            pipe.hincrby(runKey, "outputTokens", outputTokens)
            pipe.hincrbyfloat(runKey, "usd", cost)
            pipe.hincrby(runKey, f"calls:{model}", 1)
            pipe.expire(runKey, self.keepSeconds)
            pipe.hincrbyfloat("cost:total", "usd", cost)
            await pipe.execute()
        return cost

    async def runTotal(self, runId: str) -> dict[str, float | int]:
        data = await self.redis.hgetall(f"cost:run:{runId}")
        return {
            "inputTokens": int(data.get("inputTokens", 0)),
            "outputTokens": int(data.get("outputTokens", 0)),
            "usd": float(data.get("usd", 0)),
        } | {key: int(value) for key, value in data.items() if key.startswith("calls:")}
