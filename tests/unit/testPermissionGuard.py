from datetime import datetime, timezone

from libs.guardrails.agentToken import AgentClaims
from libs.guardrails.permissionGuard import PermissionGuard, RolePolicy


class TestPermissionGuard:
    guard = PermissionGuard({
        "researcher": RolePolicy(issuer="orchestrator", tools=("arxiv.*",)),
        "writer": RolePolicy(issuer="orchestrator", tools=("notes.save", "notes.read"), hours=(6, 22)),
        "nightJob": RolePolicy(issuer="orchestrator", tools=("notes.read",), hours=(22, 6)),
    })

    @staticmethod
    def claims(agent: str, issuer: str = "orchestrator") -> AgentClaims:
        return AgentClaims(agent, issuer, "run1", "trace1")

    @staticmethod
    def at(hour: int) -> datetime:
        return datetime(2026, 10, 30, hour, tzinfo=timezone.utc)

    def testAllowsScopedTool(self):
        assert self.guard.checkCall(self.claims("researcher"), "arxiv.search").allowed

    def testDeniesToolOutsideScope(self):
        verdict = self.guard.checkCall(self.claims("researcher"), "notes.save")
        assert not verdict.allowed
        assert "may not call" in verdict.reason

    def testWildcardIsCaseSensitive(self):
        assert not self.guard.checkCall(self.claims("researcher"), "ARXIV.search").allowed

    def testDeniesUnknownAgent(self):
        assert not self.guard.checkCall(self.claims("admin"), "notes.save").allowed

    def testDeniesWrongIssuer(self):
        assert not self.guard.checkCall(self.claims("writer", issuer="factChecker"), "notes.save").allowed

    def testTimeWindow(self):
        assert self.guard.checkCall(self.claims("writer"), "notes.save", self.at(10)).allowed
        assert not self.guard.checkCall(self.claims("writer"), "notes.save", self.at(23)).allowed

    def testTimeWindowAcrossMidnight(self):
        assert self.guard.checkCall(self.claims("nightJob"), "notes.read", self.at(23)).allowed
        assert self.guard.checkCall(self.claims("nightJob"), "notes.read", self.at(3)).allowed
        assert not self.guard.checkCall(self.claims("nightJob"), "notes.read", self.at(12)).allowed
