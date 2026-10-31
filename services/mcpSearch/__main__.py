from libs.serviceRunner import ServiceRunner
from libs.settings import Settings
from services.mcpSearch.searchServer import SearchServer


class SearchService:
    async def start(self) -> None:
        settings = Settings()
        server = SearchServer(settings.searchHmacKey.get_secret_value().encode(), settings.makeRedis())
        await ServiceRunner.serve(server.app(settings.searchUrl), settings.searchUrl)


if __name__ == "__main__":
    ServiceRunner.run("mcpSearch", SearchService().start)
