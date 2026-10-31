from psycopg_pool import AsyncConnectionPool

from libs.serviceRunner import ServiceRunner
from libs.settings import Settings
from services.orchestrator.orchestratorFactory import OrchestratorFactory


class OrchestratorService:
    async def start(self) -> None:
        settings = Settings()
        async with (
            AsyncConnectionPool(settings.postgresUrl, open=False) as pool,
            OrchestratorFactory.checkpointPool(settings) as checkpointPool,
        ):
            worker = await OrchestratorFactory.worker(settings, settings.makeRedis(), pool, checkpointPool)
            await worker.runForever()


if __name__ == "__main__":
    ServiceRunner.run("orchestrator", OrchestratorService().start)
