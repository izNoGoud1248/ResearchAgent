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

    async def summary(self, days: int) -> dict[str, Any]:
        """Gateway decisions per day, refusal reasons, PII redactions and latency per tool for the last few days."""
        window = {"days": days}
        async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                """
                SELECT to_char(day, 'YYYY-MM-DD') AS day,
                       count(audit.id) FILTER (WHERE outcome = 'allowed') AS allowed,
                       count(audit.id) FILTER (WHERE outcome = 'denied') AS denied,
                       count(audit.id) FILTER (WHERE outcome = 'failed') AS failed
                FROM generate_series(date_trunc('day', now()) - (%(days)s - 1) * interval '1 day', date_trunc('day', now()), interval '1 day') AS day
                LEFT JOIN audit ON date_trunc('day', audit.at) = day
                GROUP BY day ORDER BY day
                """,
                window,
            )
            perDay = await cursor.fetchall()
            await cursor.execute(
                "SELECT reason, count(*) AS count FROM audit WHERE outcome = 'denied' AND at >= now() - %(days)s * interval '1 day' "
                "GROUP BY reason ORDER BY count DESC LIMIT 6",
                window,
            )
            refusals = await cursor.fetchall()
            await cursor.execute(
                "SELECT coalesce(sum(value::int), 0) AS redactions, count(DISTINCT audit.id) AS calls "
                "FROM audit, jsonb_each_text(pii) WHERE at >= now() - %(days)s * interval '1 day'",
                window,
            )
            pii = await cursor.fetchone()
            await cursor.execute(
                """
                SELECT tool, count(*) AS calls,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY ms) AS p50,
                       percentile_cont(0.95) WITHIN GROUP (ORDER BY ms) AS p95,
                       count(*) FILTER (WHERE outcome = 'failed') AS failed
                FROM audit WHERE outcome <> 'denied' AND at >= now() - %(days)s * interval '1 day'
                GROUP BY tool ORDER BY calls DESC
                """,
                window,
            )
            tools = await cursor.fetchall()
        return {"perDay": perDay, "refusals": refusals, "pii": pii, "tools": tools}

    async def forRun(self, run: str) -> list[dict[str, Any]]:
        async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "SELECT at, tool, outcome, ms, reason, agent, issuer, run, trace, pii FROM audit WHERE run = %s ORDER BY id",
                (run,),
            )
            return await cursor.fetchall()
