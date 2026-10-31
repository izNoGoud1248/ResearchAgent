from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

from libs.guardrails.agentToken import AgentClaims
from libs.guardrails.verdict import Verdict


@dataclass(frozen=True)
class RolePolicy:
    issuer: str
    tools: tuple[str, ...]
    hours: tuple[int, int] | None = None  # UTC, start inclusive, end exclusive, may wrap midnight


class PermissionGuard:
    def __init__(self, roles: dict[str, RolePolicy]):
        self.roles = roles

    @classmethod
    def fromFile(cls, path: Path) -> "PermissionGuard":
        data = yaml.safe_load(path.read_text())
        return cls({
            name: RolePolicy(
                issuer=role["issuer"],
                tools=tuple(role["tools"]),
                hours=tuple(role["hours"]) if "hours" in role else None,
            )
            for name, role in data["roles"].items()
        })

    def checkCall(self, claims: AgentClaims, toolName: str, now: datetime | None = None) -> Verdict:
        policy = self.roles.get(claims.agent)
        if policy is None:
            return Verdict.deny(f"unknown agent {claims.agent!r}")
        if policy.issuer != claims.issuer:
            return Verdict.deny(f"{claims.issuer!r} may not act as {claims.agent!r}")
        if not any(fnmatchcase(toolName, pattern) for pattern in policy.tools):
            return Verdict.deny(f"{claims.agent!r} may not call {toolName!r}")
        if policy.hours and not self.insideWindow(policy.hours, (now or datetime.now(timezone.utc)).hour):
            return Verdict.deny(f"{claims.agent!r} is outside its allowed hours {policy.hours}")
        return Verdict.allow()

    @staticmethod
    def insideWindow(hours: tuple[int, int], hour: int) -> bool:
        start, end = hours
        return start <= hour < end if start < end else hour >= start or hour < end
