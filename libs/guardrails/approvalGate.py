from typing import Any

from langgraph.graph import END
from langgraph.types import interrupt


class ApprovalGate:
    """Pauses the graph until a human decides. The checkpointer keeps the run while it waits.

    The reviewer can approve (save), reject (end), or request changes: their note goes back to the writer,
    the critic scores the new draft, and it returns here. Requests for changes are capped.
    """

    actions = ("approve", "revise", "reject")
    maxRevisions = 2

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        rounds = state.get("reviewRounds", 0)
        decision = interrupt({
            "runId": state["runId"],
            "draft": state["draft"],
            "reason": state.get("sensitiveReason", ""),
            "revisionsLeft": self.maxRevisions - rounds,
        })
        action = decision.get("action")
        note = str(decision.get("note", ""))
        # Anything unexpected, or a request past the cap, is treated as a rejection rather than looping.
        if action == "revise" and note and rounds < self.maxRevisions:
            return {"reviewAction": "revise", "reviewNote": note, "reviewerFeedback": note, "reviewRounds": rounds + 1}
        approved = action == "approve"
        return {"reviewAction": "approve" if approved else "reject", "approved": approved, "reviewNote": note}

    @staticmethod
    def nextStep(state: dict[str, Any]) -> str:
        action = state.get("reviewAction")
        if action == "approve":
            return "saveNote"
        if action == "revise":
            return "writer"
        return END
