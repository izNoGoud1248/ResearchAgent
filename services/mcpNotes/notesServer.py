import uuid
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from starlette.applications import Starlette

from libs.guardrails.responseValidator import ResponseSigner
from libs.telemetry.tracer import Tracer
from libs.tools.mcpTransport import McpTransport


class NotesServer:
    schema = """
CREATE TABLE IF NOT EXISTS notes (
    id uuid PRIMARY KEY,
    run text NOT NULL,
    title text NOT NULL,
    body text NOT NULL,
    created timestamptz NOT NULL DEFAULT now()
)
"""

    def __init__(self, hmacKey: bytes, pool: AsyncConnectionPool, maxBody: int = 50000):
        self.signer = ResponseSigner(hmacKey)
        self.pool = pool
        self.maxBody = maxBody
        self.server = MCPServer("mcpNotes")
        self.server.tool(name="save", description="Save a report as a note. Returns the note id.")(self.save)
        self.server.tool(name="read", description="Read a saved note by id.")(self.read)

    async def setup(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(self.schema)

    def app(self, url: str) -> Starlette:
        return self.server.streamable_http_app(stateless_http=True, json_response=True, transport_security=McpTransport.security(url))

    async def save(self, runId: str, title: str, body: str, ctx: Context) -> dict[str, Any]:
        if len(body) > self.maxBody:
            raise ToolError(f"note body is longer than {self.maxBody} characters")
        noteId = uuid.uuid4()
        with Tracer.span("mcpNotes.save", carrier=ctx.headers or {}, runId=runId):
            async with self.pool.connection() as connection:
                cursor = await connection.execute(
                    "INSERT INTO notes (id, run, title, body) VALUES (%s, %s, %s, %s) RETURNING created",
                    (noteId, runId, title[:200], body),
                )
                created, = await cursor.fetchone()
        return self.signed({"noteId": str(noteId), "runId": runId, "created": created.isoformat()})

    async def read(self, noteId: str, ctx: Context) -> dict[str, Any]:
        try:
            parsedId = uuid.UUID(noteId)
        except ValueError:
            raise ToolError(f"{noteId!r} is not a valid note id") from None
        with Tracer.span("mcpNotes.read", carrier=ctx.headers or {}):
            async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("SELECT id, run, title, body, created FROM notes WHERE id = %s", (parsedId,))
                row = await cursor.fetchone()
        if row is None:
            raise ToolError(f"note {noteId} not found")
        return self.signed({
            "noteId": str(row["id"]),
            "runId": row["run"],
            "title": row["title"],
            "body": row["body"],
            "created": row["created"].isoformat(),
        })

    def signed(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"payload": payload, "signature": self.signer.sign(payload)}
