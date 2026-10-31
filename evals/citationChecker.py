import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from libs.tools.gatewayClient import GatewayClient


@dataclass
class CitationResult:
    cited: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    invented: list[str] = field(default_factory=list)
    titleChecked: int = 0
    titleMatched: int = 0
    titleMismatches: list[dict[str, str]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        cited = len(self.cited)
        return {
            "citations": cited,
            "existRate": round((cited - len(self.missing)) / cited, 3) if cited else None,
            "titleMatchRate": round(self.titleMatched / self.titleChecked, 3) if self.titleChecked else None,
            "missing": self.missing,
            "invented": self.invented,
            "titleMismatches": self.titleMismatches,
        }


class CitationChecker:
    """Checks every arXiv citation in a report: does it exist, does its title match, did the research find it."""

    idPattern = re.compile(r"\d{4}\.\d{4,5}(?:v\d+)?")
    referencePattern = re.compile(r"\[([^\]]+)\]\(https?://arxiv\.org/abs/(\d{4}\.\d{4,5}(?:v\d+)?)\)")
    titleThreshold = 0.85

    def __init__(self, tools: GatewayClient):
        self.tools = tools

    @staticmethod
    def baseId(paperId: str) -> str:
        return paperId.split("v")[0]

    @classmethod
    def citedIds(cls, report: str) -> list[str]:
        return sorted({cls.baseId(match) for match in cls.idPattern.findall(report)})

    @classmethod
    def referenceTitles(cls, report: str) -> dict[str, str]:
        return {cls.baseId(paperId): title.strip() for title, paperId in cls.referencePattern.findall(report)}

    @staticmethod
    def normalize(title: str) -> str:
        return " ".join(re.sub(r"[^a-z0-9 ]", " ", title.lower()).split())

    @classmethod
    def titlesMatch(cls, written: str, actual: str) -> bool:
        return SequenceMatcher(None, cls.normalize(written), cls.normalize(actual)).ratio() >= cls.titleThreshold

    async def check(self, report: str, retrievedIds: set[str], runId: str, traceId: str) -> CitationResult:
        result = CitationResult(cited=self.citedIds(report))
        if not result.cited:
            return result
        papers: dict[str, dict[str, Any]] = {}
        # The gateway's lookup tool takes at most 20 ids per call.
        for start in range(0, len(result.cited), 20):
            batch = result.cited[start : start + 20]
            found = await self.tools.call("evaluator", runId, traceId, "arxiv.fetch", {"ids": batch})
            papers |= {self.baseId(paper["id"]): paper for paper in found["papers"]}
            result.missing += [self.baseId(paperId) for paperId in found["missing"]]

        result.invented = [paperId for paperId in result.cited if paperId not in retrievedIds]
        for paperId, written in self.referenceTitles(report).items():
            paper = papers.get(paperId)
            if paper is None:
                continue
            result.titleChecked += 1
            if self.titlesMatch(written, paper["title"]):
                result.titleMatched += 1
            else:
                result.titleMismatches.append({"id": paperId, "written": written, "actual": paper["title"]})
        return result
