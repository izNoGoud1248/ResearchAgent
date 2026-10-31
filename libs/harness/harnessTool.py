import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


class ToolRefused(Exception):
    """A tool declined the call (bad input, permission, not found). The message goes back to the model to act on."""


@dataclass(frozen=True)
class Budget:
    maxSteps: int = 6
    maxUsd: float = 0.03
    maxSeconds: float = 120.0


@dataclass
class HarnessTool:
    """A tool the model can call: what it sees (name, description, JSON schema) and what actually runs."""

    name: str
    description: str
    parameters: dict[str, Any]
    run: Callable[[dict[str, Any]], Awaitable[Any]]
    # A one-line stand-in for a result once it is old enough to be compacted out of the context.
    digest: Callable[[Any], str] = field(default=lambda result: f"{len(json.dumps(result, default=str))} characters")
    maxResultChars: int = 6000

    def schema(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


@dataclass
class HarnessStep:
    number: int
    tool: str
    arguments: dict[str, Any]
    outcome: str  # ok, refused, error, repeated, invalid
    note: str = ""


@dataclass
class HarnessResult:
    output: dict[str, Any] | None
    stopReason: str  # finished, budgetSteps, budgetUsd, budgetSeconds, stuck, noFinish
    steps: list[HarnessStep]
    usd: float
    seconds: float
