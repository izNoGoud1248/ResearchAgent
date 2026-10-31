from psycopg_pool import AsyncConnectionPool

from libs.serviceRunner import ServiceRunner
from libs.settings import Settings
from services.mcpNotes.notesServer import NotesServer


class NotesService:
    async def start(self) -> None:
        settings = Settings()
        async with AsyncConnectionPool(settings.postgresUrl, open=False) as pool:
            server = NotesServer(settings.notesHmacKey.get_secret_value().encode(), pool)
            await server.setup()
            await ServiceRunner.serve(server.app(settings.notesUrl), settings.notesUrl)


if __name__ == "__main__":
    ServiceRunner.run("mcpNotes", NotesService().start)
