from dataclasses import asdict, dataclass, field
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


@dataclass
class AuditEntry:
    tool: str
    outcome: str  # allowed, denied or failed
    ms: int
    reason: str = ""
    agent: str = ""
    issuer: str = ""
    run: str = ""
    trace: str = ""
    pii: dict[str, int] = field(default_factory=dict)


class AuditLog:
    schema = """
CREATE TABLE IF NOT EXISTS audit (
    id bigserial PRIMARY KEY,
    at timestamptz NOT NULL DEFAULT now(),
    tool text NOT NULL,
    outcome text NOT NULL,
    ms integer NOT NULL,
    reason text NOT NULL,
    agent text NOT NULL,
    issuer text NOT NULL,
    run text NOT NULL,
    trace text NOT NULL,
    pii jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS auditRunIndex ON audit (run);
"""

    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    async def setup(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(self.schema)

    async def record(self, entry: AuditEntry) -> None:
        values = asdict(entry) | {"pii": Jsonb(entry.pii)}
        async with self.pool.connection() as connection:
            await connection.execute(
                "INSERT INTO audit (tool, outcome, ms, reason, agent, issuer, run, trace, pii) "
                "VALUES (%(tool)s, %(outcome)s, %(ms)s, %(reason)s, %(agent)s, %(issuer)s, %(run)s, %(trace)s, %(pii)s)",
                values,
            )

    async def recent(self, outcome: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "SELECT id, at, tool, outcome, ms, reason, agent, issuer, run, trace, pii FROM audit "
                "WHERE %(outcome)s::text IS NULL OR outcome = %(outcome)s ORDER BY id DESC LIMIT %(limit)s",
                {"outcome": outcome, "limit": limit},
            )
            return await cursor.fetchall()

    async def forRun(self, run: str) -> list[dict[str, Any]]:
        async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "SELECT at, tool, outcome, ms, reason, agent, issuer, run, trace, pii FROM audit WHERE run = %s ORDER BY id",
                (run,),
            )
            return await cursor.fetchall()
