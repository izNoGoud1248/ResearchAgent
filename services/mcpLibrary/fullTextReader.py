import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup, Tag

from libs.reliability.rateLimiter import RateLimiter


@dataclass(frozen=True)
class Passage:
    section: str
    position: int
    body: str


class FullTextReader:
    """Reads a paper's HTML version from arXiv and splits it into its own sections, then into passages.

    Not every paper has an HTML version (older ones, or LaTeX that did not convert); those return None and
    the library keeps only the abstract.
    """

    skippedSections = re.compile(r"acknowledg|ethic|funding|author contribution|open science", re.IGNORECASE)
    passageChars = 1400
    overlapChars = 200

    def __init__(self, limiter: RateLimiter, timeout: float = 30.0):
        self.limiter = limiter
        self.timeout = timeout

    async def read(self, paperId: str) -> list[Passage] | None:
        # Same arXiv rate limit as search: one request every three seconds, shared across replicas.
        await self.limiter.acquire("global")
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as http:
            response = await http.get(f"https://arxiv.org/html/{paperId}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return self.passages(response.text)

    def passages(self, html: str) -> list[Passage]:
        soup = BeautifulSoup(html, "html.parser")
        for unwanted in soup.select(".ltx_bibliography, section.ltx_appendix, .ltx_note, .ltx_tag_note"):
            unwanted.decompose()
        sections: list[tuple[str, str]] = []
        abstract = soup.select_one(".ltx_abstract")
        if abstract:
            sections.append(("Abstract", self.text(abstract, dropTitle=True)))
        for section in soup.select("section.ltx_section"):
            title = self.title(section)
            if title and not self.skippedSections.search(title):
                sections.append((title, self.text(section, dropTitle=True)))
        return [passage for name, body in sections for passage in self.split(name, body)]

    @staticmethod
    def title(section: Tag) -> str:
        heading = section.find(["h2", "h3"])
        # "3 Model Architecture" or "4. Experiments" -> "Model Architecture"; only section numbers are removed.
        return re.sub(r"^\d+(\.\d+)*\.?\s+", "", " ".join(heading.get_text(" ", strip=True).split())) if heading else ""

    @staticmethod
    def text(element: Tag, dropTitle: bool) -> str:
        if dropTitle and (heading := element.find(["h2", "h3", "h6"])):
            heading.extract()
        return " ".join(element.get_text(" ", strip=True).split())

    def split(self, section: str, body: str) -> list[Passage]:
        """Cuts a section into passages of about passageChars, ending on a sentence where possible, with overlap."""
        passages, start, position = [], 0, 0
        while start < len(body):
            end = min(len(body), start + self.passageChars)
            if end < len(body):
                sentenceEnd = body.rfind(". ", start + self.passageChars // 2, end)
                end = sentenceEnd + 1 if sentenceEnd != -1 else end
            passages.append(Passage(section, position, body[start:end].strip()))
            position += 1
            if end >= len(body):
                break
            start = max(end - self.overlapChars, start + 1)
        return [passage for passage in passages if len(passage.body) > 40]
