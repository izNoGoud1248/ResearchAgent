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
    """Planner -> researchers in parallel -> fact-check (A2A) -> writer <-> critic -> sensitivity -> approval -> save.

    At approval a reviewer can also send the draft back to the writer with notes.
    """

    def __init__(
        self,
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
        self.critic = critic
        self.sensitivity = sensitivity
        self.approval = approval
        self.nodes: dict[str, NodeAction] = {
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
        graph.add_edge(START, "planner")
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
        return [
            Send("researcher", {"runId": state["runId"], "traceId": state["traceId"], "mode": state.get("researcherMode", "workflow"), **part})
            for part in state["plan"]
        ]

    def withEvents(self, name: str, action: NodeAction) -> NodeAction:
        async def run(state: Any) -> dict[str, Any]:
            with Tracer.span(f"agent.{name}", expected=(GraphBubbleUp,), runId=state["runId"]):
                await self.events.publish(state["runId"], "nodeStarted", node=name)
                update = await action(state)
                await self.events.publish(state["runId"], "nodeFinished", node=name, update=self.describe(update))
                return update

        return run

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
