from services.orchestrator.agents.clarifier import Clarifier
from services.orchestrator.agents.planner import Planner


class TestClarifier:
    def testAskKeepsQuestionAndAtMostFourOptions(self):
        decision = Clarifier.decision({"status": "ask", "question": "Did you mean JEPA?", "options": ["JEPA", "a", "b", "c", "d"]})
        assert decision == {"clarifyStatus": "ask", "clarifyQuestion": {"question": "Did you mean JEPA?", "options": ["JEPA", "a", "b", "c"]}}
        assert Clarifier.nextStep(decision) == "askUser"

    def testAssumptionIsKept(self):
        decision = Clarifier.decision({"status": "assume", "assumption": "JEV is taken to mean JEPA."})
        assert decision == {"clarifyStatus": "assume", "assumption": "JEV is taken to mean JEPA."}
        assert Clarifier.nextStep(decision) == "planner"

    def testIncompleteOrUnknownRepliesCountAsClear(self):
        for reply in ({"status": "ask"}, {"status": "assume", "assumption": " "}, {"status": "maybe"}, {}):
            assert Clarifier.decision(reply) == {"clarifyStatus": "clear"}

    def testPlannerSeesTheClarification(self):
        state = {"question": "Compare RLCD and JEV models", "clarification": "Did you mean JEPA? Answer: JEPA"}
        assert Planner.request(state) == "Compare RLCD and JEV models\nThe user clarified: Did you mean JEPA? Answer: JEPA"
