import json
from dataclasses import asdict, dataclass
from typing import Any

import openai
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from redis.asyncio import Redis

from libs.llm.costTracker import CostTracker
from libs.llm.modelRouter import ModelRouter
from libs.llm.responseCache import ResponseCache
from libs.reliability.circuitBreaker import CircuitBreaker
from libs.reliability.rateLimiter import RateLimiter
from libs.reliability.retrier import Retrier
from libs.settings import Settings
from libs.telemetry.tracer import Tracer


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text written by the model; untrusted until parsed


@dataclass(frozen=True)
class LlmReply:
    text: str
    model: str
    inputTokens: int
    outputTokens: int
    cost: float = 0.0
    cached: bool = False
    toolCalls: tuple[ToolCall, ...] = ()

    @classmethod
    def fromStored(cls, stored: dict[str, Any], **changes: Any) -> "LlmReply":
        calls = tuple(ToolCall(**call) for call in stored.get("toolCalls", ()))
        return cls(**(stored | {"toolCalls": calls} | changes))


class LlmClient:
    # Worth retrying and counting against the breaker. A bad request is our bug, not an outage.
    transientErrors = (
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.InternalServerError,
        TimeoutError,
    )

    def __init__(
        self,
        openaiClient: AsyncOpenAI,
        router: ModelRouter,
        cache: ResponseCache,
        costTracker: CostTracker,
        limiter: RateLimiter,
        breaker: CircuitBreaker,
        retrier: Retrier,
        embeddingModel: str = "text-embedding-3-small",
        embeddingClient: AsyncOpenAI | None = None,
    ):
        self.embeddingModel = embeddingModel
        self.openai = openaiClient
        self.embedder = embeddingClient or openaiClient
        self.router = router
        self.cache = cache
        self.costTracker = costTracker
        self.limiter = limiter
        self.breaker = breaker
        self.retrier = retrier

    @classmethod
    def fromSettings(cls, settings: Settings, redis: Redis) -> "LlmClient":
        perMinute = settings.openaiRequestsPerMinute
        # Without a key the client cannot be built; embedding calls then fail with an authentication error.
        openaiKey = settings.openaiApiKey.get_secret_value() if settings.openaiApiKey else "not-set"
        openaiClient = AsyncOpenAI(api_key=openaiKey, max_retries=0)
        chatClient = AsyncOpenAI(base_url=settings.llmBaseUrl, api_key=openaiKey, max_retries=0) if settings.llmBaseUrl else openaiClient
        local = frozenset({settings.cheapModel, settings.strongModel}) if settings.llmBaseUrl else frozenset()
        return cls(
            chatClient,
            ModelRouter(settings.cheapModel, settings.strongModel),
            ResponseCache(redis, "llm", ttl=86400),
            CostTracker(redis, freeModels=local),
            RateLimiter(redis, "openai", capacity=perMinute, refillPerSecond=perMinute / 60),
            CircuitBreaker(redis, "openai", countOn=cls.transientErrors),
            Retrier(attempts=3, timeout=settings.llmTimeoutSeconds, retryOn=cls.transientErrors),
            embeddingClient=openaiClient,
        )

    async def complete(
        self,
        task: str,
        messages: list[dict[str, Any]],
        runId: str,
        jsonMode: bool = False,
        temperature: float = 0.0,
        tools: list[dict[str, Any]] | None = None,
        toolChoice: str | dict[str, Any] = "auto",
    ) -> LlmReply:
        """One model call. With tools, the reply may carry tool calls instead of (or as well as) text."""
        model = self.router.pick(task, sum(len(str(message.get("content") or "")) for message in messages))
        request: dict[str, Any] = {"model": model, "messages": messages, "jsonMode": jsonMode, "temperature": temperature}
        if tools:
            request |= {"tools": tools, "toolChoice": toolChoice}

        # Attribute names follow the OpenTelemetry GenAI conventions and Langfuse's, so it shows as a generation.
        with Tracer.span(
            f"llm.{task}",
            runId=runId,
            **{
                "langfuse.observation.type": "generation",
                "langfuse.observation.input": json.dumps(messages),
                "gen_ai.operation.name": "chat",
                "gen_ai.request.model": model,
            },
        ) as span:
            reply = await self.answer(request, runId)
            span.set_attributes({
                "gen_ai.response.model": reply.model,
                "gen_ai.usage.input_tokens": reply.inputTokens,
                "gen_ai.usage.output_tokens": reply.outputTokens,
                "langfuse.observation.output": reply.text or json.dumps([asdict(call) for call in reply.toolCalls]),
                "llm.toolCalls": len(reply.toolCalls),
                "llm.cached": reply.cached,
                "llm.costUsd": reply.cost,
            })
            return reply

    async def answer(self, request: dict[str, Any], runId: str) -> LlmReply:
        # Only deterministic requests are safe to replay from cache.
        useCache = request["temperature"] == 0
        if useCache:
            cached = await self.cache.get(request)
            if cached is not None:
                return LlmReply.fromStored(cached, cost=0.0, cached=True)

        await self.limiter.acquire("global")
        response = await self.breaker.call(lambda: self.retrier.run(lambda: self.send(request)))

        usage = response.usage
        message = response.choices[0].message
        reply = LlmReply(
            text=message.content or "",
            model=response.model,
            inputTokens=usage.prompt_tokens,
            outputTokens=usage.completion_tokens,
            toolCalls=tuple(ToolCall(call.id, call.function.name, call.function.arguments) for call in message.tool_calls or []),
        )
        cost = await self.costTracker.record(runId, reply.model, reply.inputTokens, reply.outputTokens)
        if useCache:
            await self.cache.set(request, asdict(reply))
        return LlmReply.fromStored(asdict(reply), cost=cost)

    async def embed(self, texts: list[str], runId: str) -> list[list[float]]:
        """Embeds texts in one request. Not cached in Redis: the library stores every vector it computes."""
        if not texts:
            return []
        with Tracer.span("llm.embed", runId=runId, texts=len(texts), **{"gen_ai.request.model": self.embeddingModel}) as span:
            await self.limiter.acquire("global")
            response = await self.breaker.call(
                lambda: self.retrier.run(lambda: self.embedder.embeddings.create(model=self.embeddingModel, input=texts))
            )
            cost = await self.costTracker.record(runId, response.model, response.usage.prompt_tokens, 0)
            span.set_attributes({"gen_ai.usage.input_tokens": response.usage.prompt_tokens, "llm.costUsd": cost})
        return [item.embedding for item in sorted(response.data, key=lambda item: item.index)]

    async def send(self, request: dict[str, Any]) -> ChatCompletion:
        options: dict[str, Any] = {"response_format": {"type": "json_object"}} if request["jsonMode"] else {}
        if request.get("tools"):
            options |= {"tools": request["tools"], "tool_choice": request["toolChoice"]}
        return await self.openai.chat.completions.create(
            model=request["model"],
            messages=request["messages"],
            temperature=request["temperature"],
            **options,
        )
