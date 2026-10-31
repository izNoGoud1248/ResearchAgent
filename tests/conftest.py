import asyncio
import sys

import psycopg
import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from psycopg_pool import AsyncConnectionPool

from libs.settings import Settings
from libs.telemetry.tracer import Tracer

testDatabase = 15


def pytest_asyncio_loop_factories(config, item):
    # psycopg's async mode cannot run on the Windows proactor loop.
    if sys.platform == "win32":
        return {"selector": asyncio.SelectorEventLoop}
    return None


@pytest.fixture(scope="session")
def spans() -> InMemorySpanExporter:
    exporter = InMemorySpanExporter()
    Tracer.setup("tests", exporter=exporter)
    return exporter


@pytest.fixture(autouse=True)
def tracing(spans: InMemorySpanExporter) -> InMemorySpanExporter:
    spans.clear()
    return spans


class ScratchDatabase:
    """Tests write runs, notes, audit rows and checkpoints, so they get their own Postgres database."""

    name = "researchdesktest"

    @classmethod
    def settingsFor(cls, base: Settings) -> Settings:
        with psycopg.connect(base.postgresUrl, autocommit=True) as connection:
            exists = connection.execute("SELECT 1 FROM pg_database WHERE datname = %s", (cls.name,)).fetchone()
            if not exists:
                connection.execute(f"CREATE DATABASE {cls.name}")
        return base.model_copy(update={"postgresDb": cls.name})


@pytest.fixture(scope="session")
def settings() -> Settings:
    return ScratchDatabase.settingsFor(Settings())


@pytest.fixture
async def redis(settings: Settings):
    client = settings.makeRedis(db=testDatabase)
    await client.flushdb()
    yield client
    await client.flushdb()
    await client.aclose()


@pytest.fixture
async def pool(settings: Settings):
    async with AsyncConnectionPool(settings.postgresUrl, open=False) as connections:
        yield connections
