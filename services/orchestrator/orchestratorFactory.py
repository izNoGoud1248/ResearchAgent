from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from redis.asyncio import Redis

from libs.guardrails.agentToken import AgentTokenIssuer
from libs.guardrails.approvalGate import ApprovalGate
from libs.llm.costTracker import CostTracker
from libs.llm.llmClient import LlmClient
from libs.reliability.heartbeat import Heartbeat
from libs.reliability.jobQueue import JobQueue
from libs.runEvents import RunEvents
from libs.settings import Settings
from libs.tools.a2aClient import A2aClient
from libs.tools.gatewayClient import GatewayClient
from services.orchestrator.agents.agentResearcher import AgentResearcher
from services.orchestrator.agents.critic import Critic
from services.orchestrator.agents.clarifier import Clarifier
from services.orchestrator.reportSkills import ReportSkills
from services.orchestrator.agents.factCheckStep import FactCheckStep
from services.orchestrator.agents.noteSaver import NoteSaver
from services.orchestrator.agents.planner import Planner
from services.orchestrator.agents.researcher import Researcher
from services.orchestrator.agents.researcherSwitch import ResearcherSwitch
from services.orchestrator.agents.sensitivityCheck import SensitivityCheck
from services.orchestrator.agents.writer import Writer
from services.orchestrator.orchestratorWorker import OrchestratorWorker
from services.orchestrator.researchGraph import ResearchGraph
from services.orchestrator.runStore import RunStore


class OrchestratorFactory:
    queueName = "research"

    @staticmethod
    def checkpointPool(settings: Settings) -> AsyncConnectionPool:
        # The LangGraph saver needs autocommit connections that return rows as dicts.
        return AsyncConnectionPool(
            settings.postgresUrl, open=False, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row}
        )

    @classmethod
    async def worker(
        cls,
        settings: Settings,
        redis: Redis,
        pool: AsyncConnectionPool,
        checkpointPool: AsyncConnectionPool,
        gatewayUrl: str | None = None,
        factCheckerUrl: str | None = None,
    ) -> OrchestratorWorker:
        llm = LlmClient.fromSettings(settings, redis)
        events = RunEvents(redis)
        issuer = AgentTokenIssuer(settings.decodeKey(settings.agentSigningSeed.get_secret_value()))
        tools = GatewayClient(gatewayUrl or settings.gatewayUrl, issuer)
        factChecker = A2aClient(factCheckerUrl or settings.factCheckerUrl, issuer, audience="factChecker", timeout=settings.a2aTimeoutSeconds)

        skills = ReportSkills()
        graph = ResearchGraph(
            clarifier=Clarifier(llm, tools),
            planner=Planner(llm, skills),
            researcher=ResearcherSwitch(Researcher(llm, tools, events), AgentResearcher(llm, tools, events)),
            factCheck=FactCheckStep(factChecker, events),
            writer=Writer(llm, skills),
            critic=Critic(llm, skills),
            sensitivity=SensitivityCheck(llm),
            approval=ApprovalGate(),
            noteSaver=NoteSaver(tools, events),
            events=events,
        )
        checkpointer = AsyncPostgresSaver(checkpointPool)
        await checkpointer.setup()
        runs = RunStore(pool)
        await runs.setup()
        return OrchestratorWorker(graph.compile(checkpointer), cls.queue(redis), runs, events, CostTracker(redis), Heartbeat(redis))

    @classmethod
    def queue(cls, redis: Redis) -> JobQueue:
        return JobQueue(redis, cls.queueName, maxDepth=50)
