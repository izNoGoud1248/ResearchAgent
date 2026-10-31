import json
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sse_starlette import EventSourceResponse

from libs.guardrails.approvalGate import ApprovalGate
from libs.guardrails.inputGuard import InputGuard
from libs.llm.responseCache import ResponseCache
from libs.reliability.circuitBreaker import CircuitBreaker
from libs.reliability.heartbeat import Heartbeat
from libs.reliability.jobQueue import JobQueue, QueueFullError
from libs.reliability.rateLimiter import RateLimiter
from libs.runEvents import RunEvents
from libs.settings import Settings
from libs.telemetry.jsonLogger import JsonLogger
from libs.telemetry.tracer import Tracer
from services.api.apiAuth import ApiAuth
from services.api.followUpAnswerer import FollowUpAnswerer
from services.mcpGateway.auditLog import AuditLog
from services.orchestrator.runStore import RunStore


class AskRequest(BaseModel):
    question: str
    sensitive: bool = False
    # workflow: fixed search-then-summarize researchers. agent: researchers that choose their own tool calls.
    researcher: Literal["workflow", "agent"] | None = None


class DecisionRequest(BaseModel):
    action: Literal["approve", "revise", "reject"]
    note: str = Field("", max_length=2000)


class SignInRequest(BaseModel):
    apiKey: str = Field(max_length=200)


class FollowUpRequest(BaseModel):
    question: str = Field(max_length=1000)


class ApiApp:
    breakerNames = ("openai", "tool:mcpSearch", "tool:mcpNotes", "tool:mcpLibrary")
    cacheNames = ("llm", "arxiv")

    def __init__(
        self,
        settings: Settings,
        redis: Redis,
        runs: RunStore,
        queue: JobQueue,
        audit: AuditLog,
        askPerMinute: int = 10,
        followUp: FollowUpAnswerer | None = None,
    ):
        self.auth = ApiAuth(settings)
        self.redis = redis
        self.researcherMode = settings.researcherMode
        self.guard = InputGuard()
        self.limiter = RateLimiter(redis, "api", capacity=askPerMinute, refillPerSecond=askPerMinute / 60)
        self.runs = runs
        self.queue = queue
        self.audit = audit
        self.followUp = followUp
        self.events = RunEvents(redis)
        self.breakers = [CircuitBreaker(redis, name) for name in self.breakerNames]
        self.caches = {name: ResponseCache(redis, name) for name in self.cacheNames}
        self.links = {"jaeger": settings.jaegerUrl, "kibana": settings.kibanaUrl, "langfuse": settings.langfuseProjectUrl}
        self.log = JsonLogger("api")

        self.app = FastAPI(title="ResearchDesk API")
        FastAPIInstrumentor.instrument_app(self.app, excluded_urls="health,runs/.*/events")
        self.app.add_api_route("/health", self.health, methods=["GET"])
        self.app.add_api_route("/me", self.me, methods=["GET"])
        self.app.add_api_route("/session", self.signIn, methods=["POST"])
        self.app.add_api_route("/session", self.signOut, methods=["DELETE"], status_code=204)
        self.app.add_api_route("/ops/status", self.opsStatus, methods=["GET"])
        self.app.add_api_route("/audit", self.auditFeed, methods=["GET"])
        self.app.add_api_route("/runs", self.ask, methods=["POST"], status_code=202)
        self.app.add_api_route("/runs", self.listRuns, methods=["GET"])
        self.app.add_api_route("/runs/{runId}", self.getRun, methods=["GET"])
        self.app.add_api_route("/runs/{runId}/events", self.streamEvents, methods=["GET"])
        self.app.add_api_route("/runs/{runId}/decision", self.decide, methods=["POST"], status_code=202)
        self.app.add_api_route("/runs/{runId}/ask", self.askFollowUp, methods=["POST"])

    async def askFollowUp(self, runId: str, body: FollowUpRequest, request: Request) -> Any:
        role = self.auth.require(request, "user")
        if self.followUp is None:
            raise HTTPException(status_code=503, detail="follow-up questions are not configured")
        verdict = self.guard.checkMessage(body.question)
        if not verdict.allowed:
            raise HTTPException(status_code=400, detail=verdict.reason)
        acquired = await self.limiter.tryAcquire(role)
        if not acquired.allowed:
            return self.retryLater(429, "too many questions, slow down", acquired.retryAfter)
        run = await self.existingRun(runId)
        if not run["report"]:
            raise HTTPException(status_code=409, detail="this run has no report yet")
        with Tracer.span("run.followUp", carrier={"traceparent": run["trace"]}, runId=runId):
            result = await self.followUp.answer(run | {"traceId": Tracer.traceIdFrom(run["trace"])}, self.guard.normalize(body.question).strip())
            self.log.info("follow-up answered", runId=runId, sources=len(result["sources"]), papersWithFullText=result["papersWithFullText"])
        return result

    async def health(self) -> dict[str, str]:
        return {"status": "ok"}

    async def me(self, request: Request) -> dict[str, str]:
        return {"role": self.auth.roleFor(request)}

    async def signIn(self, body: SignInRequest, response: Response) -> dict[str, str]:
        role = self.auth.roleForKey(body.apiKey)
        if role is None:
            raise HTTPException(status_code=401, detail="missing or unknown API key")
        self.auth.sessions.attach(response, role)
        self.log.info("browser sign-in", role=role)
        return {"role": role}

    async def signOut(self, response: Response) -> None:
        self.auth.sessions.clear(response)

    async def opsStatus(self, request: Request) -> dict[str, Any]:
        self.auth.require(request, "user")
        return {
            "workers": await Heartbeat.liveWorkers(self.redis),
            "queue": await self.queue.depth(),
            "breakers": {breaker.name: await breaker.state() for breaker in self.breakers},
            "caches": {name: await cache.stats() for name, cache in self.caches.items()},
            "links": self.links,
        }

    async def auditFeed(self, request: Request, outcome: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        self.auth.require(request, "user")
        return await self.audit.recent(outcome, min(limit, 500))

    async def ask(self, body: AskRequest, request: Request) -> Any:
        role = self.auth.require(request, "user")
        verdict = self.guard.checkMessage(body.question)
        if not verdict.allowed:
            raise HTTPException(status_code=400, detail=verdict.reason)
        acquired = await self.limiter.tryAcquire(role)
        if not acquired.allowed:
            return self.retryLater(429, "too many questions, slow down", acquired.retryAfter)

        runId = uuid.uuid4().hex
        question = self.guard.normalize(body.question).strip()
        # This span starts the run's trace. The worker continues it from the traceparent carried in the job.
        with Tracer.span("run.enqueue", runId=runId, sensitive=body.sensitive):
            traceContext = Tracer.inject()
            payload = {
                "kind": "start",
                "runId": runId,
                "traceContext": traceContext,
                "input": {
                    "runId": runId,
                    "traceId": Tracer.currentTraceId(),
                    "question": question,
                    "sensitive": body.sensitive,
                    "researcherMode": body.researcher or self.researcherMode,
                },
            }
            await self.runs.create(runId, question, body.sensitive, traceContext["traceparent"])
            try:
                await self.queue.push(payload, "normal")
            except QueueFullError as error:
                await self.runs.update(runId, status="failed", error=str(error))
                self.log.warning("queue full, run refused", runId=runId)
                return self.retryLater(503, str(error), 30)
            self.log.info("run queued", runId=runId, sensitive=body.sensitive)
        return {"runId": runId, "status": "queued"}

    async def listRuns(self, request: Request, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        self.auth.require(request, "user")
        return await self.runs.list(status, min(limit, 200))

    async def getRun(self, runId: str, request: Request) -> dict[str, Any]:
        self.auth.require(request, "user")
        run = await self.existingRun(runId)
        return run | {
            "traceId": Tracer.traceIdFrom(run["trace"]),
            "revisionsLeft": max(0, ApprovalGate.maxRevisions - run["revisions"]),
        }

    async def decide(self, runId: str, body: DecisionRequest, request: Request) -> dict[str, str]:
        self.auth.require(request, "approver")
        run = await self.existingRun(runId)
        if run["status"] != "awaitingApproval":
            raise HTTPException(status_code=409, detail=f"run is {run['status']}, not awaiting approval")
        if body.action == "revise" and not body.note.strip():
            raise HTTPException(status_code=400, detail="say what should change: a note is required to request changes")
        if body.action == "revise" and run["revisions"] >= ApprovalGate.maxRevisions:
            raise HTTPException(status_code=409, detail=f"already revised {run['revisions']} times; approve or reject")
        await self.runs.update(runId, status="resuming")
        # Approvals jump the queue: a person is waiting on them. The resume stays in the run's original trace.
        job = {"kind": "resume", "runId": runId, "decision": body.model_dump(), "traceContext": {"traceparent": run["trace"]}}
        await self.queue.push(job, "high")
        with Tracer.span("run.decision", carrier=job["traceContext"], runId=runId, action=body.action):
            self.log.info("approval decision", runId=runId, action=body.action)
        return {"runId": runId, "status": "resuming"}

    async def streamEvents(self, runId: str, request: Request) -> EventSourceResponse:
        self.auth.require(request, "user")
        await self.existingRun(runId)
        return EventSourceResponse(self.eventStream(runId, request.headers.get("last-event-id", "0"), request))

    async def eventStream(self, runId: str, lastId: str, request: Request) -> AsyncIterator[dict[str, str]]:
        while not await request.is_disconnected():
            for event in await self.events.read(runId, lastId):
                lastId = event["id"]
                yield {"id": event["id"], "event": event["kind"], "data": json.dumps(event["data"])}
                if event["kind"] in RunEvents.finalKinds:
                    return

    async def existingRun(self, runId: str) -> dict[str, Any]:
        run = await self.runs.get(runId)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    @staticmethod
    def retryLater(status: int, detail: str, seconds: float) -> JSONResponse:
        return JSONResponse({"detail": detail}, status_code=status, headers={"Retry-After": str(max(1, round(seconds)))})
