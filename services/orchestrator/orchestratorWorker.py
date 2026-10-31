import asyncio
import contextlib
import signal
from typing import Any

from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from opentelemetry.trace import StatusCode

from libs.llm.costTracker import CostTracker
from libs.reliability.heartbeat import Heartbeat
from libs.reliability.jobQueue import Job, JobQueue
from libs.runEvents import RunEvents
from libs.telemetry.jsonLogger import JsonLogger
from libs.telemetry.tracer import Tracer
from services.orchestrator.runStore import RunStore


class OrchestratorWorker:
    """Takes jobs from the queue and drives the graph. Two kinds: start a run, or resume one after approval."""

    maxConcurrency = 4

    def __init__(
        self, graph: CompiledStateGraph, queue: JobQueue, runs: RunStore, events: RunEvents, costs: CostTracker, heartbeat: Heartbeat
    ):
        self.graph = graph
        self.queue = queue
        self.runs = runs
        self.events = events
        self.costs = costs
        self.heartbeat = heartbeat
        self.stopping = asyncio.Event()
        self.log = JsonLogger("orchestrator")

    async def runForever(self, pollInterval: float = 0.5) -> None:
        """Works until asked to stop. On SIGTERM it finishes the current run, takes no new one, and exits."""
        self.stopOnSignals()
        beating = asyncio.create_task(self.heartbeat.run())
        self.log.info("worker started")
        try:
            while not self.stopping.is_set():
                await self.queue.requeueExpired()
                job = await self.queue.pop()
                if job is None:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self.stopping.wait(), pollInterval)
                    continue
                await self.handle(job)
        finally:
            beating.cancel()
            await self.heartbeat.stop()
            self.log.info("worker stopped cleanly")

    def stopOnSignals(self) -> None:
        loop = asyncio.get_running_loop()
        for signalNumber in (signal.SIGTERM, signal.SIGINT):
            # Windows event loops have no signal handlers; Ctrl+C still ends the process there.
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(signalNumber, self.stopping.set)

    async def handle(self, job: Job) -> None:
        runId = job.payload["runId"]
        kind = job.payload["kind"]
        config = {"configurable": {"thread_id": runId}, "max_concurrency": self.maxConcurrency}
        spanAttributes = {"runId": runId, "langfuse.session.id": runId, "langfuse.trace.name": "research run"}
        with Tracer.span(f"run.{kind}", carrier=job.payload.get("traceContext"), **spanAttributes) as span:
            try:
                await self.runs.update(runId, status="running")
                await self.events.publish(runId, "runStarted", job=kind)
                self.log.info("run started", runId=runId, job=kind)
                result = await self.graph.ainvoke(await self.graphInput(job, config), config)
                await self.finish(runId, result)
            except Exception as error:
                # Any failure in an agent, tool or model call ends this run, not the worker.
                reason = f"{type(error).__name__}: {error}"
                span.record_exception(error)
                span.set_status(StatusCode.ERROR, reason[:200])
                await self.runs.update(runId, status="failed", error=reason[:2000], cost=await self.costs.runTotal(runId))
                await self.events.publish(runId, "runFailed", error=reason[:500])
                self.log.error("run failed", runId=runId, error=reason[:2000])
            finally:
                await self.queue.ack(job)

    async def graphInput(self, job: Job, config: dict[str, Any]) -> Any:
        if job.payload["kind"] == "resume":
            return Command(resume=job.payload["decision"])
        # A job requeued after a worker crash continues from its last checkpoint instead of starting over.
        snapshot = await self.graph.aget_state(config)
        return None if snapshot.next else job.payload["input"]

    async def finish(self, runId: str, result: dict[str, Any]) -> None:
        cost = await self.costs.runTotal(runId)
        rounds = result.get("reviewRounds", 0)
        if result.get("__interrupt__"):
            await self.runs.update(
                runId, status="awaitingApproval", report=result["draft"], review=result.get("reviewNote", ""),
                revisions=rounds, cost=cost,
            )
            await self.events.publish(runId, "awaitingApproval", reason=result.get("sensitiveReason", ""), revision=rounds)
            self.log.info("run awaiting approval", runId=runId, revision=rounds, usd=cost["usd"])
            return
        status = "rejected" if result.get("reviewAction") == "reject" else "completed"
        await self.runs.update(
            runId, status=status, report=result.get("draft", ""), note=result.get("noteId", ""),
            review=result.get("reviewNote", ""), revisions=rounds, cost=cost,
        )
        await self.events.publish(runId, "runFinished", status=status, noteId=result.get("noteId", ""), cost=cost)
        self.log.info("run finished", runId=runId, status=status, usd=cost["usd"])
