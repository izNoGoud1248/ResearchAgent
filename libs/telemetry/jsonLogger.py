import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from libs.telemetry.tracer import Tracer


class JsonFormatter(logging.Formatter):
    """One JSON object per line with the current trace id, so Kibana can join logs to Jaeger traces."""

    def __init__(self, serviceName: str):
        super().__init__()
        self.serviceName = serviceName

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname.lower(),
            "service": self.serviceName,
            "logger": record.name,
            "message": record.getMessage(),
        }
        traceId = Tracer.currentTraceId()
        if traceId != "0" * 32:
            entry["traceId"] = traceId
            entry["spanId"] = Tracer.currentSpanId()
        entry |= getattr(record, "fields", {})
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class JsonLogger:
    logDirectory = Path(__file__).resolve().parents[2] / "logs"

    def __init__(self, name: str):
        self.logger = logging.getLogger(f"researchdesk.{name}")

    @classmethod
    def setup(cls, serviceName: str, toFile: bool = True) -> None:
        formatter = JsonFormatter(serviceName)
        handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
        if toFile:
            cls.logDirectory.mkdir(exist_ok=True)
            handlers.append(logging.FileHandler(cls.logDirectory / f"{serviceName}.log", encoding="utf-8"))
        root = logging.getLogger("researchdesk")
        root.handlers.clear()
        for handler in handlers:
            handler.setFormatter(formatter)
            root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False

    def info(self, message: str, **fields: Any) -> None:
        self.logger.info(message, extra={"fields": fields})

    def warning(self, message: str, **fields: Any) -> None:
        self.logger.warning(message, extra={"fields": fields})

    def error(self, message: str, **fields: Any) -> None:
        self.logger.error(message, extra={"fields": fields})
