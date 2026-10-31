import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

import httpx
import yaml
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from evals.citationChecker import CitationChecker
from evals.reportJudge import ReportJudge
from libs.guardrails.agentToken import AgentTokenIssuer
from libs.llm.llmClient import LlmClient
from libs.settings import Settings
from libs.tools.gatewayClient import GatewayClient
from services.orchestrator.orchestratorFactory import OrchestratorFactory

evalsDirectory = Path(__file__).resolve().parent
resultsDirectory = evalsDirectory / "results"


class RunDriver:
    """Drives the running system through its public API, as a user and an approver would."""

    finalStatuses = ("completed", "rejected", "failed")

    def __init__(self, settings: Settings):
        self.client = httpx.AsyncClient(base_url=settings.apiUrl, timeout=30)
        self.userHeaders = {"X-Api-Key": settings.userApiKey.get_secret_value()}
        self.approverHeaders = {"X-Api-Key": settings.approverApiKey.get_secret_value()}

    async def start(self, question: str, researcher: str) -> str:
        body = {"question": question, "sensitive": False, "researcher": researcher}
        response = await self.client.post("/runs", json=body, headers=self.userHeaders)
        response.raise_for_status()
        return response.json()["runId"]

    async def waitForResult(self, runId: str, timeoutSeconds: int = 900) -> dict[str, Any]:
        deadline = time.monotonic() + timeoutSeconds
        while time.monotonic() < deadline:
            run = (await self.client.get(f"/runs/{runId}", headers=self.userHeaders)).json()
            if run["status"] in self.finalStatuses:
                return run
            if run["status"] == "awaitingApproval":
                # The harness measures research quality, so held reports are approved as they are.
                await self.client.post(f"/runs/{runId}/decision", json={"action": "approve", "note": "evaluation"}, headers=self.approverHeaders)
            await asyncio.sleep(3)
        raise TimeoutError(f"run {runId} did not finish within {timeoutSeconds}s")


class RunInspector:
    """Reads a finished run's final graph state (read-only) for what the API does not expose."""

    def __init__(self, saver: AsyncPostgresSaver):
        self.saver = saver

    async def state(self, runId: str) -> dict[str, Any]:
        checkpoint = await self.saver.aget_tuple({"configurable": {"thread_id": runId}})
        return checkpoint.checkpoint["channel_values"] if checkpoint else {}


class EvalHarness:
    # Direction tells the comparison which way is better; the threshold is how much worse counts as a regression.
    metrics = {
        "completedRate": ("higher", 0.0),
        "citationExistRate": ("higher", 0.02),
        "titleMatchRate": ("higher", 0.05),
        "inventedCitations": ("lower", 0),
        "supportedRate": ("higher", 0.1),
        "criticScore": ("higher", 1.0),
        "judgeOverall": ("higher", 0.3),
        "usdPerRun": ("lower", 0.02),
        "secondsPerRun": ("lower", 60),
    }

    def __init__(self, settings: Settings, researcher: str = "workflow"):
        self.settings = settings
        self.researcher = researcher
        self.passId = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{researcher}"
        self.questions = yaml.safe_load((evalsDirectory / "questions.yaml").read_text())["questions"]

    async def run(self) -> Path:
        settings = self.settings
        redis = settings.makeRedis()
        issuer = AgentTokenIssuer(settings.decodeKey(settings.agentSigningSeed.get_secret_value()))
        checker = CitationChecker(GatewayClient(settings.gatewayUrl, issuer))
        judge = ReportJudge(LlmClient.fromSettings(settings, redis))
        driver = RunDriver(settings)

        print(f"pass {self.passId}: {len(self.questions)} questions with the {self.researcher} researcher, one at a time")
        async with OrchestratorFactory.checkpointPool(settings) as checkpointPool:
            inspector = RunInspector(AsyncPostgresSaver(checkpointPool))
            results = []
            for question in self.questions:
                runId = await driver.start(question, self.researcher)
                run = await driver.waitForResult(runId)
                results.append(await self.score(question, run, await inspector.state(runId), checker, judge))
                print(f"  scored: {question[:60]}")
        await redis.aclose()

        summary = self.aggregate(results)
        report = {"passId": self.passId, "researcher": self.researcher, "summary": summary, "runs": results}
        resultsDirectory.mkdir(exist_ok=True)
        previous = self.previousPass()
        path = resultsDirectory / f"{self.passId}.json"
        path.write_text(json.dumps(report, indent=2, default=str))
        self.printReport(results, summary, previous)
        return path

    async def score(
        self, question: str, run: dict[str, Any], state: dict[str, Any], checker: CitationChecker, judge: ReportJudge
    ) -> dict[str, Any]:
        report = run.get("report", "")
        retrieved = {CitationChecker.baseId(paper["id"]) for finding in state.get("findings", []) for paper in finding["papers"]}
        verdicts = [item["verdict"] for item in state.get("verdicts", [])]
        citations = await checker.check(report, retrieved, f"eval-{self.passId}", run.get("traceId", "eval"))
        grade = await judge.grade(question, report, f"eval-{self.passId}") if report else {"overall": None}
        started, finished = datetime.fromisoformat(run["created"]), datetime.fromisoformat(run["updated"])
        return {
            "question": question,
            "runId": run["id"],
            "traceId": run.get("traceId", ""),
            "status": run["status"],
            "seconds": round((finished - started).total_seconds(), 1),
            "usd": round(run["cost"].get("usd", 0.0), 5),
            "drafts": state.get("drafts"),
            "criticScore": state.get("critique", {}).get("score"),
            "claims": len(verdicts),
            "supportedRate": round(verdicts.count("supported") / len(verdicts), 3) if verdicts else None,
            "citations": citations.summary(),
            "judge": grade,
        }

    @staticmethod
    def average(values: list[Any]) -> float | None:
        numbers = [value for value in values if isinstance(value, (int, float))]
        return round(mean(numbers), 4) if numbers else None

    def aggregate(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "questions": len(results),
            "completedRate": round(sum(1 for item in results if item["status"] == "completed") / len(results), 3),
            "citationExistRate": self.average([item["citations"]["existRate"] for item in results]),
            "titleMatchRate": self.average([item["citations"]["titleMatchRate"] for item in results]),
            "inventedCitations": sum(len(item["citations"]["invented"]) for item in results),
            "supportedRate": self.average([item["supportedRate"] for item in results]),
            "criticScore": self.average([item["criticScore"] for item in results]),
            "judgeOverall": self.average([item["judge"]["overall"] for item in results]),
            "usdPerRun": self.average([item["usd"] for item in results]),
            "secondsPerRun": self.average([item["seconds"] for item in results]),
        }

    def previousPass(self) -> dict[str, Any] | None:
        # Compare like with like: only earlier passes that used the same researcher.
        earlier = [json.loads(path.read_text()) for path in sorted(resultsDirectory.glob("*.json")) if path.stem < self.passId]
        same = [result for result in earlier if result.get("researcher", "workflow") == self.researcher]
        return same[-1] if same else None

    def printReport(self, results: list[dict[str, Any]], summary: dict[str, Any], previous: dict[str, Any] | None) -> None:
        print(f"\n{'question':48} {'status':10} {'cites':>5} {'exist':>6} {'title':>6} {'inv':>4} {'supp':>5} {'critic':>6} {'judge':>6} {'usd':>8} {'secs':>6}")
        for item in results:
            citations = item["citations"]
            print(
                f"{item['question'][:48]:48} {item['status']:10} {citations['citations']:>5} "
                f"{self.show(citations['existRate']):>6} {self.show(citations['titleMatchRate']):>6} {len(citations['invented']):>4} "
                f"{self.show(item['supportedRate']):>5} {self.show(item['criticScore']):>6} {self.show(item['judge']['overall']):>6} "
                f"{item['usd']:>8.4f} {item['seconds']:>6.0f}"
            )
        oldSummary = previous["summary"] if previous else {}
        print(f"\nsummary{'' if previous is None else ' (vs pass ' + previous['passId'] + ')'}")
        regressions = []
        for name, (direction, threshold) in self.metrics.items():
            now, before = summary.get(name), oldSummary.get(name)
            line = f"  {name:18} {self.show(now):>10}"
            if isinstance(now, (int, float)) and isinstance(before, (int, float)):
                change = now - before
                worse = change < -threshold if direction == "higher" else change > threshold
                line += f"   was {self.show(before):>8}   {'REGRESSION' if worse else ''}"
                if worse:
                    regressions.append(name)
            print(line)
        print(f"\n{len(regressions)} regression(s): {', '.join(regressions)}" if regressions else "\nno regressions")

    @staticmethod
    def show(value: Any) -> str:
        return "-" if value is None else f"{value:.3g}" if isinstance(value, float) else str(value)


if __name__ == "__main__":
    loopFactory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    researcher = sys.argv[sys.argv.index("--researcher") + 1] if "--researcher" in sys.argv else "workflow"
    print(asyncio.run(EvalHarness(Settings(), researcher).run(), loop_factory=loopFactory))
