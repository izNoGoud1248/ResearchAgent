import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from libs.reliability.rateLimiter import RateLimiter


@dataclass(frozen=True)
class Passage:
    section: str
    position: int
    body: str


@dataclass(frozen=True)
class Figure:
    label: str
    caption: str
    imageUrl: str
    section: str

    def asDict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FullText:
    passages: list[Passage]
    figures: list[Figure]


class FullTextReader:
    """Reads a paper's HTML version from arXiv and splits it into its own sections, then into passages.

    Not every paper has an HTML version (older ones, or LaTeX that did not convert); those return None and
    the library keeps only the abstract.
    """

    skippedSections = re.compile(r"acknowledg|ethic|funding|author contribution|open science", re.IGNORECASE)
    passageChars = 1400
    overlapChars = 200
    maxFigures = 8

    def __init__(self, limiter: RateLimiter, timeout: float = 30.0):
        self.limiter = limiter
        self.timeout = timeout

    async def read(self, paperId: str) -> FullText | None:
        # Same arXiv rate limit as search: one request every three seconds, shared across replicas.
        await self.limiter.acquire("global")
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as http:
            response = await http.get(f"https://arxiv.org/html/{paperId}")
        if response.status_code == 404:
            return None
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        # Image paths are relative to the page, which arXiv may have redirected to a versioned address.
        figures = self.figures(soup, str(response.url))
        return FullText(self.passages(soup), figures)

    def figures(self, soup: BeautifulSoup, pageUrl: str) -> list[Figure]:
        """Top-level figures with an image and a numbered caption; sub-figures belong to their parent."""
        found = []
        for figure in soup.select("figure.ltx_figure"):
            if figure.find_parent("figure"):
                continue
            image = figure.select_one("img.ltx_graphics")
            caption = figure.find("figcaption", recursive=False) or figure.select_one("figcaption")
            text = " ".join(caption.get_text(" ", strip=True).split()) if caption else ""
            label = re.match(r"(Figure\s*\d+)\s*:?", text)
            if image is None or not image.get("src") or label is None:
                continue
            section = figure.find_parent("section", class_="ltx_section")
            found.append(Figure(
                label=re.sub(r"\s+", " ", label.group(1)),
                caption=text[label.end():].strip()[:400],
                imageUrl=urljoin(pageUrl, str(image["src"])),
                section=self.title(section) if section else "",
            ))
        return found[: self.maxFigures]

    def passages(self, soup: BeautifulSoup) -> list[Passage]:
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
