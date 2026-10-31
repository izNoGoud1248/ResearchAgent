import re
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool
from starlette.applications import Starlette

from libs.guardrails.responseValidator import ResponseSigner
from libs.llm.llmClient import LlmClient
from libs.telemetry.tracer import Tracer
from libs.tools.mcpTransport import McpTransport
from services.mcpLibrary.fullTextReader import FullText, FullTextReader


class LibraryServer:
    """The paper library: every paper the system has seen, with abstracts and (once read) full-text sections.

    Search is hybrid: Postgres full-text search finds exact terms ("LoRA", "HumanEval"), pgvector finds
    passages that mean the same thing in other words, and reciprocal rank fusion merges the two rankings.
    """

    schema = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS papers (
    id text PRIMARY KEY,
    version text NOT NULL,
    title text NOT NULL,
    published date,
    fulltext boolean NOT NULL DEFAULT false,
    added timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS passages (
    id bigserial PRIMARY KEY,
    paper text NOT NULL REFERENCES papers (id) ON DELETE CASCADE,
    section text NOT NULL,
    position integer NOT NULL,
    body text NOT NULL,
    embedding vector(1536) NOT NULL,
    search tsvector GENERATED ALWAYS AS (to_tsvector('english', section || ' ' || body)) STORED,
    UNIQUE (paper, section, position)
);
CREATE INDEX IF NOT EXISTS passagesEmbedding ON passages USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS passagesSearch ON passages USING gin (search);
-- NULL: not looked for yet (full text stored before figures were kept); [] means the paper has none.
ALTER TABLE papers ADD COLUMN IF NOT EXISTS figures jsonb;
"""

    searchQuery = """
WITH semantic AS (
    SELECT id, row_number() OVER (ORDER BY embedding <=> %(vector)s::vector) AS rank
    FROM passages
    WHERE %(papers)s::text[] IS NULL OR paper = ANY (%(papers)s)
    ORDER BY embedding <=> %(vector)s::vector
    LIMIT 40
),
keyword AS (
    SELECT id, row_number() OVER (ORDER BY ts_rank_cd(search, query) DESC) AS rank
    FROM passages, websearch_to_tsquery('english', %(query)s) AS query
    WHERE search @@ query AND (%(papers)s::text[] IS NULL OR paper = ANY (%(papers)s))
    ORDER BY ts_rank_cd(search, query) DESC
    LIMIT 40
)
SELECT passages.paper, papers.version, papers.title, passages.section, passages.body,
       coalesce(1.0 / (60 + semantic.rank), 0) + coalesce(1.0 / (60 + keyword.rank), 0) AS score,
       semantic.rank IS NOT NULL AS bySemantic, keyword.rank IS NOT NULL AS byKeyword
FROM passages
JOIN papers ON papers.id = passages.paper
LEFT JOIN semantic ON semantic.id = passages.id
LEFT JOIN keyword ON keyword.id = passages.id
WHERE semantic.id IS NOT NULL OR keyword.id IS NOT NULL
ORDER BY score DESC
LIMIT %(limit)s
"""

    idPattern = re.compile(r"\d{4}\.\d{4,5}(v\d+)?")

    def __init__(self, hmacKey: bytes, pool: AsyncConnectionPool, llm: LlmClient, reader: FullTextReader):
        self.signer = ResponseSigner(hmacKey)
        self.pool = pool
        self.llm = llm
        self.reader = reader
        self.server = MCPServer("mcpLibrary")
        self.server.tool(name="add", description="Add papers (id, title, published, summary) to the library.")(self.add)
        self.server.tool(name="search", description="Search stored paper passages by meaning and keywords.")(self.search)
        self.server.tool(name="read", description="Read a paper's full text by section; fetched and stored on first use.")(self.read)
        self.server.tool(name="figures", description="Figures (image link, caption, section) from papers' full text.")(self.figures)

    async def setup(self) -> None:
        async with self.pool.connection() as connection:
            await connection.execute(self.schema)

    def app(self, url: str) -> Starlette:
        return self.server.streamable_http_app(stateless_http=True, json_response=True, transport_security=McpTransport.security(url))

    @staticmethod
    def baseId(paperId: str) -> str:
        return re.sub(r"v\d+$", "", paperId.strip())

    @staticmethod
    def vectorText(vector: list[float]) -> str:
        return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"

    async def add(self, papers: list[dict[str, Any]], runId: str, ctx: Context) -> dict[str, Any]:
        """Stores each new paper with its abstract as the first passage. Papers already stored are skipped."""
        with Tracer.span("mcpLibrary.add", carrier=ctx.headers or {}, offered=len(papers)) as span:
            valid = [paper for paper in papers if self.idPattern.fullmatch(str(paper.get("id", "")).strip()) and paper.get("summary")]
            async with self.pool.connection() as connection:
                known = {row[0] for row in await (await connection.execute(
                    "SELECT id FROM papers WHERE id = ANY (%s)", ([self.baseId(paper["id"]) for paper in valid],)
                )).fetchall()}
            fresh = list({self.baseId(paper["id"]): paper for paper in valid if self.baseId(paper["id"]) not in known}.values())
            vectors = await self.llm.embed([f"{paper['title']}. {paper['summary']}" for paper in fresh], runId)
            async with self.pool.connection() as connection:
                for paper, vector in zip(fresh, vectors):
                    await connection.execute(
                        "INSERT INTO papers (id, version, title, published) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                        (self.baseId(paper["id"]), paper["id"], paper["title"][:500], paper.get("published")),
                    )
                    await connection.execute(
                        "INSERT INTO passages (paper, section, position, body, embedding) VALUES (%s, 'Abstract', 0, %s, %s::vector) "
                        "ON CONFLICT DO NOTHING",
                        (self.baseId(paper["id"]), paper["summary"], self.vectorText(vector)),
                    )
            span.set_attributes({"added": len(fresh)})
        return self.signed({"added": [paper["id"] for paper in fresh], "alreadyStored": len(valid) - len(fresh)})

    async def search(self, query: str, runId: str, ctx: Context, limit: int = 6, paperIds: list[str] | None = None) -> dict[str, Any]:
        limit = max(1, min(limit, 12))
        papers = [self.baseId(paperId) for paperId in paperIds] if paperIds else None
        with Tracer.span("mcpLibrary.search", carrier=ctx.headers or {}, query=query[:200]) as span:
            vector = (await self.llm.embed([query], runId))[0]
            async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(self.searchQuery, {"vector": self.vectorText(vector), "query": query, "papers": papers, "limit": limit})
                rows = await cursor.fetchall()
            span.set_attributes({"results": len(rows)})
        return self.signed({
            "query": query,
            "passages": [
                {
                    "paperId": row["version"], "title": row["title"], "section": row["section"], "text": row["body"],
                    "score": round(float(row["score"]), 5),
                    "matchedBy": [name for name, hit in (("meaning", row["bysemantic"]), ("keywords", row["bykeyword"])) if hit],
                }
                for row in rows
            ],
        })

    async def read(self, paperId: str, runId: str, ctx: Context, section: str | None = None) -> dict[str, Any]:
        """Without a section: the paper's section list. With one: that section's text (best match on the name)."""
        if not self.idPattern.fullmatch(paperId.strip()):
            raise ToolError(f"{paperId!r} is not an arXiv id")
        base = self.baseId(paperId)
        with Tracer.span("mcpLibrary.read", carrier=ctx.headers or {}, paperId=base):
            available = await self.ensureFullText(base, runId)
            async with self.pool.connection() as connection, connection.cursor(row_factory=dict_row) as cursor:
                await cursor.execute(
                    "SELECT section, position, body FROM passages WHERE paper = %s ORDER BY id", (base,)
                )
                rows = await cursor.fetchall()
        sections = list(dict.fromkeys(row["section"] for row in rows))
        if section is None:
            return self.signed({"paperId": paperId, "fullText": available, "sections": sections})
        wanted = next((name for name in sections if name.lower() == section.lower()), None) or next(
            (name for name in sections if section.lower() in name.lower()), None
        )
        if wanted is None:
            raise ToolError(f"no section like {section!r}; sections are: {', '.join(sections)}")
        # Passages overlap slightly at their edges, so a sentence may appear twice; that does not hurt reading.
        text = " ".join(row["body"] for row in rows if row["section"] == wanted)
        return self.signed({"paperId": paperId, "fullText": available, "section": wanted, "text": text[:8000]})

    maxFigurePapers = 4

    async def figures(self, paperIds: list[str], runId: str, ctx: Context) -> dict[str, Any]:
        """Figures of up to four papers already in the library, reading their full text first if needed."""
        ids = [self.baseId(paperId) for paperId in paperIds if self.idPattern.fullmatch(paperId.strip())][: self.maxFigurePapers]
        found: list[dict[str, Any]] = []
        with Tracer.span("mcpLibrary.figures", carrier=ctx.headers or {}, papers=len(ids)):
            for paperId in ids:
                try:
                    await self.ensureFullText(paperId, runId)
                except ToolError:
                    continue  # not in the library: nothing to show for it
                async with self.pool.connection() as connection:
                    row = await (await connection.execute("SELECT version, fulltext, figures FROM papers WHERE id = %s", (paperId,))).fetchone()
                version, hasFullText, figures = row
                if hasFullText and figures is None:
                    figures = await self.backfillFigures(paperId)
                found += [{"paperId": version, **figure} for figure in figures or []]
        return self.signed({"figures": found})

    async def backfillFigures(self, paperId: str) -> list[dict[str, Any]]:
        fullText = await self.reader.read(paperId)
        figures = [figure.asDict() for figure in fullText.figures] if fullText else []
        async with self.pool.connection() as connection:
            await connection.execute("UPDATE papers SET figures = %s WHERE id = %s", (Jsonb(figures), paperId))
        return figures

    async def ensureFullText(self, paperId: str, runId: str) -> bool:
        async with self.pool.connection() as connection:
            row = await (await connection.execute("SELECT fulltext FROM papers WHERE id = %s", (paperId,))).fetchone()
        if row is None:
            raise ToolError(f"paper {paperId} is not in the library yet; search for it first")
        if row[0]:
            return True
        fullText = await self.reader.read(paperId)
        if fullText is None or not fullText.passages:
            return False
        await self.store(paperId, fullText, runId)
        return True

    async def store(self, paperId: str, fullText: FullText, runId: str) -> None:
        passages = fullText.passages
        vectors: list[list[float]] = []
        # Embeddings in batches of 100 passages, well within the API's per-request limit.
        for start in range(0, len(passages), 100):
            vectors += await self.llm.embed([f"{passage.section}: {passage.body}" for passage in passages[start : start + 100]], runId)
        async with self.pool.connection() as connection:
            async with connection.transaction():
                # The stored abstract (position 0) is replaced by the full-text version of it.
                for passage, vector in zip(passages, vectors):
                    await connection.execute(
                        "INSERT INTO passages (paper, section, position, body, embedding) VALUES (%s, %s, %s, %s, %s::vector) "
                        "ON CONFLICT (paper, section, position) DO UPDATE SET body = EXCLUDED.body, embedding = EXCLUDED.embedding",
                        (paperId, passage.section, passage.position, passage.body, self.vectorText(vector)),
                    )
                await connection.execute(
                    "UPDATE papers SET fulltext = true, figures = %s WHERE id = %s",
                    (Jsonb([figure.asDict() for figure in fullText.figures]), paperId),
                )

    def signed(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"payload": payload, "signature": self.signer.sign(payload)}
