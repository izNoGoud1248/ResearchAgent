import asyncio
import sys
from pathlib import Path

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from libs.knowledge.knowledgeGraph import KnowledgeGraph
from libs.knowledge.knowledgeVault import KnowledgeVault, VaultReport
from libs.llm.llmClient import LlmClient
from libs.settings import Settings


class KnowledgeBackfill:
    """Adds the latest completed report for each question that is not in the vault yet, oldest first. Safe to run again.

    uv run python -m services.orchestrator.knowledgeBackfill
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    async def run(self) -> None:
        root = Path(self.settings.knowledgeDir)
        known = {node["meta"].get("runId") for node in KnowledgeGraph(root).build()["nodes"] if node["type"] == "report"}
        redis = self.settings.makeRedis()
        vault = KnowledgeVault(root, LlmClient.fromSettings(self.settings, redis))
        async with AsyncConnectionPool(self.settings.postgresUrl, open=False) as pool, AsyncPostgresSaver.from_conn_string(self.settings.postgresUrl) as saver:
            async with pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
                # Evaluation passes ask the same questions many times; the latest report per question is enough.
                await cursor.execute(
                    "SELECT * FROM (SELECT DISTINCT ON (question) id, question, report, created FROM runs "
                    "WHERE status = 'completed' AND report LIKE '%arxiv.org%' ORDER BY question, created DESC) latest ORDER BY created"
                )
                runs = [run for run in await cursor.fetchall() if run["id"] not in known]
            print(f"{len(runs)} reports to add ({len(known)} already in the vault)")
            for run in runs:
                checkpoint = await saver.aget_tuple({"configurable": {"thread_id": run["id"]}})
                state = checkpoint.checkpoint["channel_values"] if checkpoint else {}
                record = VaultReport(
                    runId=run["id"],
                    question=run["question"],
                    report=run["report"],
                    created=run["created"],
                    style=state.get("reportSkill", ""),
                    papers=[paper for finding in state.get("findings", []) for paper in finding["papers"]],
                )
                print(f"  {(await vault.add(record)).name}")
        await redis.aclose()


if __name__ == "__main__":
    if sys.platform == "win32":
        # psycopg's async mode cannot run on the Windows proactor loop.
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(KnowledgeBackfill(Settings()).run())
