import io
import json
import logging
import uuid

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from libs.settings import Settings
from libs.telemetry.jsonLogger import JsonFormatter, JsonLogger
from libs.telemetry.tracer import Tracer
from libs.tools.gatewayClient import ToolCallError
from tests.integration.conftest import ApiHarness, ToolStack


class TestTracePropagation:
    async def testOneTraceCrossesAgentGatewayAndToolServer(self, toolStack: ToolStack, tracing: InMemorySpanExporter):
        runId = uuid.uuid4().hex
        with Tracer.span("test.run"):
            traceId = Tracer.currentTraceId()
            await toolStack.client.call("researcher", runId, traceId, "arxiv.search", {"query": "agent tracing", "maxResults": 2})

        spans = {span.name: span for span in tracing.get_finished_spans()}
        for name in ("tool.arxiv.search", "gateway.arxiv.search", "mcpSearch.search"):
            assert format(spans[name].context.trace_id, "032x") == traceId, name
        # The gateway span is a child of the agent's tool span, across a real HTTP hop.
        assert spans["gateway.arxiv.search"].parent.span_id == spans["tool.arxiv.search"].context.span_id
        assert spans["gateway.arxiv.search"].attributes["outcome"] == "allowed"

        audit = await toolStack.audit.forRun(runId)
        assert audit[0]["trace"] == traceId

    async def testRefusalIsRecordedButNotAnError(self, toolStack: ToolStack, tracing: InMemorySpanExporter):
        with Tracer.span("test.run"), pytest.raises(ToolCallError):
            await toolStack.client.call("researcher", uuid.uuid4().hex, Tracer.currentTraceId(), "notes.save", {"title": "x", "body": "y"})

        gateway = next(span for span in tracing.get_finished_spans() if span.name == "gateway.notes.save")
        assert gateway.attributes["outcome"] == "denied"
        assert gateway.status.status_code != StatusCode.ERROR

    async def testApiStartsTheTraceAndHandsItToTheWorker(self, settings: Settings, redis, pool):
        harness = ApiHarness(settings, redis, pool)
        await harness.runs.setup()
        async with harness.client() as client:
            runId = (await client.post("/runs", json={"question": "Tracing agents"}, headers=harness.userHeaders)).json()["runId"]
            run = (await client.get(f"/runs/{runId}", headers=harness.userHeaders)).json()

        job = await harness.queue.pop()
        assert Tracer.traceIdFrom(job.payload["traceContext"]["traceparent"]) == run["traceId"]
        assert job.payload["input"]["traceId"] == run["traceId"]
        assert len(run["traceId"]) == 32 and run["traceId"] != "0" * 32


class TestJsonLogs:
    def testLogLineCarriesTraceAndFields(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter("tests"))
        logger = logging.getLogger("researchdesk.telemetryTest")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        with Tracer.span("test.log"):
            traceId = Tracer.currentTraceId()
            JsonLogger("telemetryTest").info("run queued", runId="run1", sensitive=True)

        entry = json.loads(stream.getvalue().strip().splitlines()[-1])
        assert entry["message"] == "run queued"
        assert entry["traceId"] == traceId
        assert entry["runId"] == "run1" and entry["sensitive"] is True
        assert entry["service"] == "tests" and entry["level"] == "info"
