import json

from libs.harness.agentHarness import AgentHarness
from libs.harness.gatewayToolbox import GatewayToolbox
from libs.harness.harnessTool import Budget, HarnessTool, ToolRefused
from libs.llm.llmClient import ToolCall


class Library:
    """A small real tool for the harness to run: looks up books, refuses empty titles."""

    def __init__(self):
        self.calls = 0

    async def find(self, arguments: dict) -> dict:
        self.calls += 1
        if not arguments.get("title"):
            raise ToolRefused("title is required")
        return {"title": arguments["title"], "text": "x" * 500}


class TestAgentHarnessMechanics:
    def build(self, library: Library, **options) -> AgentHarness:
        tool = HarnessTool(
            name="findBook",
            description="Find a book by title.",
            parameters={"type": "object", "properties": {"title": {"type": "string"}}},
            run=library.find,
            digest=lambda result: f"book {result['title']}",
            maxResultChars=200,
        )
        finish = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}
        return AgentHarness(None, "test", "instructions", [tool], finish, **options)

    async def testRepeatedCallIsNotExecutedAgain(self):
        library = Library()
        harness = self.build(library)
        seen: dict[str, str] = {}
        first, step = await harness.execute(ToolCall("1", "findBook", '{"title": "Dune"}'), 1, seen)
        again, repeat = await harness.execute(ToolCall("2", "findBook", '{"title":"Dune"}'), 2, seen)
        assert step.outcome == "ok" and repeat.outcome == "repeated"
        assert library.calls == 1
        assert "Earlier result" in again

    async def testRefusalsAndMistakesGoBackToTheModel(self):
        harness = self.build(Library())
        refused, step = await harness.execute(ToolCall("1", "findBook", "{}"), 1, {})
        assert refused == "refused: title is required" and step.outcome == "refused"
        badJson, step = await harness.execute(ToolCall("2", "findBook", "{title: Dune"), 2, {})
        assert badJson.startswith("error: arguments were not valid JSON") and step.outcome == "error"
        unknown, step = await harness.execute(ToolCall("3", "deleteEverything", "{}"), 3, {})
        assert "unknown tool" in unknown and "findBook" in unknown

    async def testLongResultsAreTruncatedForTheModel(self):
        content, step = await self.build(Library()).execute(ToolCall("1", "findBook", '{"title": "Dune"}'), 1, {})
        assert len(content) < 260 and "[truncated" in content
        assert step.note == "book Dune"

    def testFinishNeedsItsRequiredFields(self):
        harness = self.build(Library())
        assert harness.parseFinish(ToolCall("1", "finish", '{"answer": "42"}')) == ({"answer": "42"}, "")
        output, problem = harness.parseFinish(ToolCall("2", "finish", "{}"))
        assert output is None and "missing ['answer']" in problem

    def testBudgetsAreChecked(self):
        harness = self.build(Library(), budget=Budget(maxSteps=3, maxUsd=0.01, maxSeconds=5))
        assert harness.exhaustedBudget(2, 0.005, 1) is None
        assert harness.exhaustedBudget(3, 0.0, 0) == "budgetSteps"
        assert harness.exhaustedBudget(0, 0.02, 0) == "budgetUsd"
        assert harness.exhaustedBudget(0, 0.0, 9) == "budgetSeconds"

    def testOldToolResultsAreCompactedButTheLatestStayWhole(self):
        harness = self.build(Library(), contextChars=1000)
        messages = [{"role": "system", "content": "s"}] + [
            {"role": "tool", "tool_call_id": str(index), "content": json.dumps({"n": index, "text": "y" * 600})} for index in range(4)
        ]
        harness.compact(messages)
        tools = [message for message in messages if message["role"] == "tool"]
        assert tools[0]["content"].startswith("[compacted]")
        assert not tools[-1]["content"].startswith("[compacted]") and not tools[-2]["content"].startswith("[compacted]")

    def testGatewayToolNamesBecomeValidFunctionNames(self):
        assert GatewayToolbox.functionName("arxiv.search") == "arxivSearch"
        assert GatewayToolbox.functionName("notes.save") == "notesSave"
