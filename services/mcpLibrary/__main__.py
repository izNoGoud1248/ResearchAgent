from psycopg_pool import AsyncConnectionPool

from libs.llm.llmClient import LlmClient
from libs.reliability.rateLimiter import RateLimiter
from libs.serviceRunner import ServiceRunner
from libs.settings import Settings
from services.mcpLibrary.fullTextReader import FullTextReader
from services.mcpLibrary.libraryServer import LibraryServer


class LibraryService:
    async def start(self) -> None:
        settings = Settings()
        redis = settings.makeRedis()
        async with AsyncConnectionPool(settings.postgresUrl, open=False) as pool:
            reader = FullTextReader(RateLimiter(redis, "arxiv", capacity=1, refillPerSecond=1 / 3))
            server = LibraryServer(settings.libraryHmacKey.get_secret_value().encode(), pool, LlmClient.fromSettings(settings, redis), reader)
            await server.setup()
            await ServiceRunner.serve(server.app(settings.libraryUrl), settings.libraryUrl)


if __name__ == "__main__":
    ServiceRunner.run("mcpLibrary", LibraryService().start)
