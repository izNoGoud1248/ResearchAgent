from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from libs.guardrails.approvalGate import ApprovalGate
from libs.runEvents import RunEvents
from libs.telemetry.tracer import Tracer
from services.orchestrator.agents.clarifier import Clarifier, ClarifyingQuestion
from services.orchestrator.agents.critic import Critic
from services.orchestrator.agents.factCheckStep import FactCheckStep
from services.orchestrator.agents.noteSaver import NoteSaver
from services.orchestrator.agents.planner import Planner
from services.orchestrator.agents.researcherSwitch import ResearcherSwitch
from services.orchestrator.agents.sensitivityCheck import SensitivityCheck
from services.orchestrator.agents.writer import Writer
from services.orchestrator.researchState import ResearchState

NodeAction = Callable[[Any], Awaitable[dict[str, Any]]]


class ResearchGraph:
    """Clarifier (may ask the user) -> planner -> researchers in parallel -> fact-check (A2A) -> writer <-> critic -> sensitivity -> approval -> save.

    At approval a reviewer can also send the draft back to the writer with notes.
    """

    def __init__(
        self,
        clarifier: Clarifier,
        planner: Planner,
        researcher: ResearcherSwitch,
        factCheck: FactCheckStep,
        writer: Writer,
        critic: Critic,
        sensitivity: SensitivityCheck,
        approval: ApprovalGate,
        noteSaver: NoteSaver,
        events: RunEvents,
    ):
        self.events = events
        self.clarifier = clarifier
        self.critic = critic
        self.sensitivity = sensitivity
        self.approval = approval
        self.nodes: dict[str, NodeAction] = {
            "clarify": clarifier.run,
            "askUser": ClarifyingQuestion().run,
            "planner": planner.run,
            "researcher": researcher.run,
            "factCheck": factCheck.run,
            "writer": writer.run,
            "critic": critic.run,
            "sensitivity": sensitivity.run,
            "approval": approval.run,
            "saveNote": noteSaver.run,
        }

    def compile(self, checkpointer: BaseCheckpointSaver) -> CompiledStateGraph:
        graph = StateGraph(ResearchState)
        for name, action in self.nodes.items():
            graph.add_node(name, self.withEvents(name, action))
        graph.add_edge(START, "clarify")
        graph.add_conditional_edges("clarify", self.clarifier.nextStep, ["askUser", "planner"])
        graph.add_edge("askUser", "planner")
        graph.add_conditional_edges("planner", self.fanOut, ["researcher"])
        graph.add_edge("researcher", "factCheck")
        graph.add_edge("factCheck", "writer")
        graph.add_edge("writer", "critic")
        graph.add_conditional_edges("critic", self.critic.nextStep, ["writer", "sensitivity"])
        graph.add_conditional_edges("sensitivity", self.sensitivity.nextStep, ["approval", "saveNote"])
        graph.add_conditional_edges("approval", self.approval.nextStep, ["saveNote", "writer", END])
        graph.add_edge("saveNote", END)
        return graph.compile(checkpointer=checkpointer)

    @staticmethod
    def fanOut(state: ResearchState) -> list[Send]:
        mode = state.get("researcherMode", "workflow")
        return [
            Send("researcher", {"runId": state["runId"], "traceId": state["traceId"], "mode": mode, "part": number, **part})
            for number, part in enumerate(state["plan"], start=1)
        ]

    def withEvents(self, name: str, action: NodeAction) -> NodeAction:
        async def run(state: Any) -> dict[str, Any]:
            with Tracer.span(f"agent.{name}", expected=(GraphBubbleUp,), runId=state["runId"]):
                lane = self.lane(name, state)
                await self.events.publish(state["runId"], "nodeStarted", node=name, **lane)
                update = await action(state)
                if lane:
                    lane["papers"] = sum(len(finding["papers"]) for finding in update.get("findings", []))
                await self.events.publish(state["runId"], "nodeFinished", node=name, update=self.describe(update), **lane)
                return update

        return run

    @staticmethod
    def lane(name: str, state: Any) -> dict[str, Any]:
        # Parallel researchers share one node name; their sub-question number tells them apart in the live view.
        return {"part": state["part"], "question": state["question"]} if name == "researcher" else {}

    @staticmethod
    def describe(update: dict[str, Any]) -> dict[str, Any]:
        # Small summaries for the live view; the full state stays in the checkpoint.
        summary: dict[str, Any] = {}
        for key, value in update.items():
            if key == "draft":
                summary["draftPreview"] = value[:400]
            elif isinstance(value, list):
                summary[key] = len(value)
            else:
                summary[key] = value
        return summary
