import operator
from typing import Annotated, Any, TypedDict


class ResearchTask(TypedDict):
    runId: str
    traceId: str
    question: str
    searchQuery: str
    mode: str  # workflow or agent, see ResearcherSwitch


class ResearchState(TypedDict, total=False):
    runId: str
    traceId: str
    question: str
    sensitive: bool
    researcherMode: str
    clarifyStatus: str  # clear, assume or ask, see Clarifier
    clarifyQuestion: dict[str, Any]
    clarification: str
    assumption: str
    sensitiveReason: str
    plan: list[dict[str, str]]
    findings: Annotated[list[dict[str, Any]], operator.add]
    verdicts: list[dict[str, Any]]
    draft: str
    drafts: int
    critique: dict[str, Any]
    approved: bool
    reviewAction: str
    reviewNote: str
    reviewerFeedback: str
    reviewRounds: int
    noteId: str
