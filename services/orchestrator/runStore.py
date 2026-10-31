from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool


class RunStore:
    schema = """
CREATE TABLE IF NOT EXISTS runs (
    id text PRIMARY KEY,
    question text NOT NULL,
    sensitive boolean NOT NULL,
    status text NOT NULL,
    created timestamptz NOT NULL DEFAULT now(),
    updated timestamptz NOT NULL DEFAULT now(),
    report text NOT NULL DEFAULT '',
    note text NOT NULL DEFAULT '',
    review text NOT NULL DEFAULT '',
    cost jsonb NOT NULL DEFAULT '{}',
    error text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS runsStatusIndex ON runs (status, created DESC);
ALTER TABLE runs ADD COLUMN IF NOT EXISTS trace text NOT NULL DEFAULT '';
ALTER TABLE runs ADD COLUMN IF NOT EXISTS revisions integer NOT NULL DEFAULT 0;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS clarification jsonb NOT NULL DEFAULT '{}';
"""
    columns = ("status", "sensitive", "report", "note", "review", "cost", "error", "revisions", "clarification")
    jsonColumns = ("cost", "clarification")
    statuses = ("queued", "running", "awaitingClarification", "awaitingApproval", "resuming", "completed", "rejected", "failed")

    def __init__(self, pool: AsyncConnectionPool):
        self.pool = pool

    async def setup(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(self.schema)

    async def create(self, runId: str, question: str, sensitive: bool, trace: str) -> None:
        """trace is the run's W3C traceparent, so a resumed run joins the same trace."""
        async with self.pool.connection() as connection:
            await connection.execute(
                "INSERT INTO runs (id, question, sensitive, status, trace) VALUES (%s, %s, %s, 'queued', %s)",
                (runId, question, sensitive, trace),
            )

    async def update(self, runId: str, **fields: Any) -> None:
        unknown = set(fields) - set(self.columns)
        if unknown:
            raise ValueError(f"unknown run fields {sorted(unknown)}")
        values = {name: Jsonb(value) if name in self.jsonColumns else value for name, value in fields.items()}
        assignments = ", ".join(f"{name} = %({name})s" for name in values)
        async with self.pool.connection() as connection:
            await connection.execute(f"UPDATE runs SET {assignments}, updated = now() WHERE id = %(runId)s", values | {"runId": runId})

    async def get(self, runId: str) -> dict[str, Any] | None:
        async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute("SELECT * FROM runs WHERE id = %s", (runId,))
            return await cursor.fetchone()

    async def daily(self, days: int) -> dict[str, Any]:
        """Runs and spend per day for the last few days, every day present even when empty."""
        async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                """
                SELECT to_char(day, 'YYYY-MM-DD') AS day,
                       count(runs.id) FILTER (WHERE status = 'completed') AS completed,
                       count(runs.id) FILTER (WHERE status = 'rejected') AS rejected,
                       count(runs.id) FILTER (WHERE status = 'failed') AS failed,
                       count(runs.id) FILTER (WHERE status NOT IN ('completed', 'rejected', 'failed')) AS open,
                       coalesce(sum((runs.cost->>'usd')::float), 0) AS usd
                FROM generate_series(date_trunc('day', now()) - (%(days)s - 1) * interval '1 day', date_trunc('day', now()), interval '1 day') AS day
                LEFT JOIN runs ON date_trunc('day', runs.created) = day
                GROUP BY day ORDER BY day
                """,
                {"days": days},
            )
            perDay = await cursor.fetchall()
            await cursor.execute(
                "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY extract(epoch FROM updated - created)) AS median "
                "FROM runs WHERE status = 'completed' AND created >= now() - %(days)s * interval '1 day'",
                {"days": days},
            )
            median = (await cursor.fetchone())["median"]
        return {"perDay": perDay, "medianSeconds": median}

    async def list(self, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
            await cursor.execute(
                "SELECT id, question, sensitive, status, created, updated, note, cost, error, revisions FROM runs "
                "WHERE %(status)s::text IS NULL OR status = %(status)s ORDER BY created DESC LIMIT %(limit)s",
                {"status": status, "limit": limit},
            )
            return await cursor.fetchall()
