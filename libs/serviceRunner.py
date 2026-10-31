import asyncio
import sys
from collections.abc import Callable, Coroutine
from typing import Any
from urllib.parse import urlparse

import uvicorn
from starlette.types import ASGIApp

from libs.settings import Settings
from libs.telemetry.jsonLogger import JsonLogger
from libs.telemetry.tracer import Tracer


class ServiceRunner:
    """Starts a service: JSON logs, tracing to the collector, then its async main.

    Windows needs the selector loop because psycopg cannot use the proactor loop.
    """

    @staticmethod
    def run(serviceName: str, main: Callable[[], Coroutine[Any, Any, None]]) -> None:
        settings = Settings()
        JsonLogger.setup(serviceName)
        provider = Tracer.setup(serviceName, endpoint=settings.otlpEndpoint or None)
        loopFactory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
        try:
            asyncio.run(main(), loop_factory=loopFactory)
        finally:
            provider.shutdown()

    @staticmethod
    async def serve(app: ASGIApp, url: str, host: str = "0.0.0.0") -> None:
        config = uvicorn.Config(app, host=host, port=urlparse(url).port, log_level="info")
        await uvicorn.Server(config).serve()
