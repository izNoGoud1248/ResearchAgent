import re

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from libs.guardrails.agentToken import AgentTokenIssuer
from libs.harness.harnessTool import Budget
from libs.llm.llmClient import LlmClient
from libs.runEvents import RunEvents
from libs.settings import Settings
from libs.tools.a2aClient import A2aCallError, A2aClient
from services.factChecker.factCheckerApp import FactCheckerApp
from services.orchestrator.agents.agentResearcher import AgentResearcher
from services.orchestrator.orchestratorFactory import OrchestratorFactory
from tests.integration.conftest import ApiHarness, RunningServer, ToolStack

factCheckerUrl = "http://127.0.0.1:8204"


class TestFactCheckerAuth:
    async def testRejectsTokenMeantForTheGateway(self, settings: Settings, redis, toolStack: ToolStack):
        app = FactCheckerApp(settings, redis, gatewayUrl=toolStack.url, publicUrl=factCheckerUrl)
        issuer = AgentTokenIssuer(settings.decodeKey(settings.agentSigningSeed.get_secret_value()))
        wrongAudience = A2aClient(factCheckerUrl, issuer, audience="mcpGateway")
        async with RunningServer(app.app, 8204):
            with pytest.raises(A2aCallError, match="Audience doesn't match"):
                await wrongAudience.ask({"question": "q", "claims": ["c"]}, "run1", "trace1")


@pytest.mark.llm
class TestResearchRun:
    async def testSensitiveRunWaitsForApprovalThenSavesReport(
        self, settings: Settings, redis, pool, toolStack: ToolStack, tracing: InMemorySpanExporter
    ):
        cheap = settings.model_copy(update={"strongModel": settings.cheapModel})
        factChecker = FactCheckerApp(cheap, redis, gatewayUrl=toolStack.url, publicUrl=factCheckerUrl)
        harness = ApiHarness(cheap, redis, pool)
        await harness.runs.setup()

        async with RunningServer(factChecker.app, 8204), OrchestratorFactory.checkpointPool(cheap) as checkpointPool:
            worker = await OrchestratorFactory.worker(
                cheap, redis, pool, checkpointPool, gatewayUrl=toolStack.url, factCheckerUrl=factCheckerUrl
            )
            async with harness.client() as client:
                question = {"question": "What are the latest approaches to prompt injection defense?", "sensitive": True}
                runId = (await client.post("/runs", json=question, headers=harness.userHeaders)).json()["runId"]

                await worker.handle(await worker.queue.pop())
                waiting = (await client.get(f"/runs/{runId}", headers=harness.userHeaders)).json()
                assert waiting["status"] == "awaitingApproval", waiting["error"]
                assert "arxiv" in waiting["report"].lower()

                decision = {"action": "approve", "note": "fine to share"}
                assert (await client.post(f"/runs/{runId}/decision", json=decision, headers=harness.approverHeaders)).status_code == 202
                await worker.handle(await worker.queue.pop())
                done = (await client.get(f"/runs/{runId}", headers=harness.userHeaders)).json()

        assert done["status"] == "completed", done["error"]
        assert done["note"] and done["review"] == "fine to share"

        events = await RunEvents(redis).read(runId, "0", blockMs=10)
        started = {event["data"]["node"] for event in events if event["kind"] == "nodeStarted"}
        assert started == {"planner", "researcher", "factCheck", "writer", "critic", "sensitivity", "approval", "saveNote"}
        kinds = [event["kind"] for event in events]
        assert "a2aCall" in kinds and "awaitingApproval" in kinds and kinds[-1] == "runFinished"

        audit = await toolStack.audit.forRun(runId)
        assert {row["agent"] for row in audit} == {"researcher", "factChecker", "writer"}
        assert all(row["outcome"] == "allowed" for row in audit)

        # Start, pause, approval and resume all land in one trace, across the queue and every service.
        runSpans = [span for span in tracing.get_finished_spans() if span.attributes.get("runId") == runId]
        assert {format(span.context.trace_id, "032x") for span in runSpans} == {done["traceId"]}
        names = {span.name for span in runSpans}
        assert {"run.enqueue", "run.start", "run.resume", "agent.planner", "agent.approval", "a2a.factChecker", "llm.writer"} <= names
        approvalSpans = [span for span in runSpans if span.name == "agent.approval"]
        assert all(span.status.status_code != StatusCode.ERROR for span in approvalSpans)

        print(f"\nRun cost: ${done['cost']['usd']:.4f}, drafts: {sum(1 for e in events if e['kind'] == 'nodeStarted' and e['data']['node'] == 'writer')}")
        assert done["cost"]["usd"] > 0

    async def testRequestChangesSendsDraftBackThenRejectEndsRun(
        self, settings: Settings, redis, pool, toolStack: ToolStack, tracing: InMemorySpanExporter
    ):
        cheap = settings.model_copy(update={"strongModel": settings.cheapModel})
        factChecker = FactCheckerApp(cheap, redis, gatewayUrl=toolStack.url, publicUrl=factCheckerUrl)
        harness = ApiHarness(cheap, redis, pool)
        await harness.runs.setup()

        async with RunningServer(factChecker.app, 8204), OrchestratorFactory.checkpointPool(cheap) as checkpointPool:
            worker = await OrchestratorFactory.worker(
                cheap, redis, pool, checkpointPool, gatewayUrl=toolStack.url, factCheckerUrl=factCheckerUrl
            )
            async with harness.client() as client:
                question = {"question": "How do retrieval-augmented generation systems reduce hallucination?", "sensitive": True}
                runId = (await client.post("/runs", json=question, headers=harness.userHeaders)).json()["runId"]
                runUrl = f"/runs/{runId}"

                await worker.handle(await worker.queue.pop())
                first = (await client.get(runUrl, headers=harness.userHeaders)).json()
                assert first["status"] == "awaitingApproval", first["error"]
                assert first["revisions"] == 0 and first["revisionsLeft"] == 2

                request = "Add a section titled Limitations that lists two open problems."
                revise = {"action": "revise", "note": request}
                assert (await client.post(f"{runUrl}/decision", json=revise, headers=harness.approverHeaders)).status_code == 202
                await worker.handle(await worker.queue.pop())
                second = (await client.get(runUrl, headers=harness.userHeaders)).json()

                assert second["status"] == "awaitingApproval", second["error"]
                assert second["revisions"] == 1 and second["revisionsLeft"] == 1
                assert second["review"] == request
                assert second["report"] != first["report"]
                assert "limitation" in second["report"].lower()

                reject = {"action": "reject", "note": "not ready to share"}
                assert (await client.post(f"{runUrl}/decision", json=reject, headers=harness.approverHeaders)).status_code == 202
                await worker.handle(await worker.queue.pop())
                done = (await client.get(runUrl, headers=harness.userHeaders)).json()

        assert done["status"] == "rejected", done["error"]
        assert done["note"] == "" and done["review"] == "not ready to share"
        assert done["report"] == second["report"]

        events = await RunEvents(redis).read(runId, "0", blockMs=10)
        writerRuns = sum(1 for event in events if event["kind"] == "nodeStarted" and event["data"]["node"] == "writer")
        started = {event["data"]["node"] for event in events if event["kind"] == "nodeStarted"}
        assert writerRuns >= 2
        assert "saveNote" not in started
        # The revision reused the research: planner and researchers ran once, in the first pass only.
        assert sum(1 for event in events if event["kind"] == "nodeStarted" and event["data"]["node"] == "planner") == 1
        assert [event["data"]["status"] for event in events if event["kind"] == "runFinished"] == ["rejected"]

        audit = await toolStack.audit.forRun(runId)
        assert "notes.save" not in {row["tool"] for row in audit}
        print(f"\nRun cost: ${done['cost']['usd']:.4f}, writer runs: {writerRuns}")


@pytest.mark.llm
class TestFactCheckerVerdicts:
    claim = "The Transformer is a sequence transduction model based solely on attention, dispensing with recurrence and convolutions"

    async def testJudgesEachClaimAgainstThePaperItCites(self, settings: Settings, redis, toolStack: ToolStack):
        app = FactCheckerApp(settings, redis, gatewayUrl=toolStack.url, publicUrl=factCheckerUrl)
        issuer = AgentTokenIssuer(settings.decodeKey(settings.agentSigningSeed.get_secret_value()))
        claims = [
            f"{self.claim} [arXiv:1706.03762].",
            f"{self.claim} [arXiv:1512.03385].",
            f"{self.claim} [arXiv:2099.99999].",
        ]
        async with RunningServer(app.app, 8204):
            answer = await A2aClient(factCheckerUrl, issuer, audience="factChecker").ask(
                {"question": "How do Transformers work?", "claims": claims}, "factTest", "trace1"
            )
        verdicts = [item["verdict"] for item in answer["verdicts"]]
        for item in answer["verdicts"]:
            print(f"\n{item['verdict']:11} {item['reason'][:120]}")
        # Right paper: supported. A real but unrelated paper (ResNet) or a paper that does not exist: not supported.
        assert verdicts == ["supported", "unsupported", "unsupported"]


@pytest.mark.llm
class TestAgentResearcher:
    async def testResearchesWithItsOwnToolCallsAndCitesOnlyWhatItRetrieved(self, settings: Settings, redis, toolStack: ToolStack):
        llm = LlmClient.fromSettings(settings, redis)
        researcher = AgentResearcher(llm, toolStack.client, RunEvents(redis))
        task = {"runId": "agentTest", "traceId": "trace1", "question": "How does speculative decoding speed up LLM inference?",
                "searchQuery": "speculative decoding", "mode": "agent"}
        finding = (await researcher.run(task))["findings"][0]

        events = await RunEvents(redis).read("agentTest", "0", blockMs=10)
        finished = next(event["data"] for event in events if event["kind"] == "agentFinished")
        calls = [event["data"]["tool"] for event in events if event["kind"] == "toolCall"]
        print(f"\nagent: {finished['stopReason']} after {finished['steps']} steps, ${finished['usd']}, tools {calls}")

        assert finished["stopReason"] == "finished"
        assert calls and set(calls) <= {"arxivSearch", "arxivFetch", "paperRead", "librarySearch"}
        assert finding["summary"] and finding["claims"]
        retrieved = {paper["id"] for paper in finding["papers"]}
        for claim in finding["claims"]:
            cited = re.findall(r"\[arXiv:([^\]]+)\]", claim)
            assert cited and set(cited) <= retrieved

    async def testStepBudgetForcesAnAnswer(self, settings: Settings, redis, toolStack: ToolStack):
        llm = LlmClient.fromSettings(settings, redis)
        researcher = AgentResearcher(llm, toolStack.client, RunEvents(redis))
        researcher.budget = Budget(maxSteps=1, maxUsd=0.03, maxSeconds=150)
        task = {"runId": "agentBudget", "traceId": "trace1", "question": "What are open problems in LLM agent evaluation?",
                "searchQuery": "LLM agent evaluation", "mode": "agent"}
        finding = (await researcher.run(task))["findings"][0]
        events = await RunEvents(redis).read("agentBudget", "0", blockMs=10)
        finished = next(event["data"] for event in events if event["kind"] == "agentFinished")
        assert finished["stopReason"] == "budgetSteps"
        assert finding["summary"]
