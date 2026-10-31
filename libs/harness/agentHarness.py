import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from libs.harness.harnessTool import Budget, HarnessResult, HarnessStep, HarnessTool, ToolRefused
from libs.llm.llmClient import LlmClient, ToolCall
from libs.telemetry.tracer import Tracer

StepHook = Callable[[str, dict[str, Any]], Awaitable[None]]


class AgentHarness:
    """Runs a model in a tool-calling loop until it calls `finish`, with the guard rails an agent needs.

    - The model decides which tool to call next; the harness executes it and returns the result.
    - Budgets cap steps, spend and time; when one runs out the model must finish with what it has.
    - Errors and refusals go back to the model as text it can act on, instead of ending the run.
    - The same call made twice is not executed again; repeating three times counts as stuck.
    - Older tool results are compacted to one-line digests when the context grows too large.
    """

    finishName = "finish"
    maxRepeats = 3

    def __init__(
        self,
        llm: LlmClient,
        task: str,
        instructions: str,
        tools: list[HarnessTool],
        finishSchema: dict[str, Any],
        budget: Budget = Budget(),
        contextChars: int = 24000,
        onToolCall: StepHook | None = None,
    ):
        self.llm = llm
        self.task = task
        self.instructions = instructions
        self.tools = {tool.name: tool for tool in tools}
        self.finishSchema = finishSchema
        self.budget = budget
        self.contextChars = contextChars
        self.onToolCall = onToolCall

    def toolSchemas(self) -> list[dict[str, Any]]:
        finish = {
            "type": "function",
            "function": {
                "name": self.finishName,
                "description": "Call once you have enough evidence, or when told to stop. This ends your work.",
                "parameters": self.finishSchema,
            },
        }
        return [tool.schema() for tool in self.tools.values()] + [finish]

    async def run(self, goal: str, runId: str) -> HarnessResult:
        started = time.monotonic()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.instructions},
            {"role": "user", "content": goal},
        ]
        steps: list[HarnessStep] = []
        seen: dict[str, str] = {}
        repeats = 0
        usd = 0.0
        stopReason = "noFinish"
        mustFinish = False

        with Tracer.span(f"harness.{self.task}", runId=runId, maxSteps=self.budget.maxSteps) as span:
            for stepNumber in range(1, self.budget.maxSteps + 2):
                exhausted = self.exhaustedBudget(len(steps), usd, time.monotonic() - started)
                if exhausted and not mustFinish:
                    stopReason, mustFinish = exhausted, True
                    messages.append({"role": "user", "content": f"Budget reached ({exhausted}). Call finish now with what you have."})
                if repeats >= self.maxRepeats and not mustFinish:
                    stopReason, mustFinish = "stuck", True
                    messages.append({"role": "user", "content": "You keep repeating calls. Call finish now with what you have."})

                self.compact(messages)
                choice: str | dict[str, Any] = {"type": "function", "function": {"name": self.finishName}} if mustFinish else "required"
                reply = await self.llm.complete(self.task, messages, runId, tools=self.toolSchemas(), toolChoice=choice)
                usd += reply.cost
                assistant: dict[str, Any] = {"role": "assistant", "content": reply.text or None}
                if reply.toolCalls:
                    assistant["tool_calls"] = [
                        {"id": call.id, "type": "function", "function": {"name": call.name, "arguments": call.arguments}}
                        for call in reply.toolCalls
                    ]
                messages.append(assistant)

                for call in reply.toolCalls:
                    if call.name == self.finishName:
                        output, problem = self.parseFinish(call)
                        if output is not None:
                            stopReason = "finished" if not mustFinish else stopReason
                            steps.append(HarnessStep(stepNumber, self.finishName, output, "ok"))
                            span.set_attributes({"stopReason": stopReason, "steps": len(steps), "usd": usd})
                            return HarnessResult(output, stopReason, steps, usd, time.monotonic() - started)
                        messages.append({"role": "tool", "tool_call_id": call.id, "content": f"error: {problem}"})
                        steps.append(HarnessStep(stepNumber, self.finishName, {}, "invalid", problem))
                        continue
                    content, step = await self.execute(call, stepNumber, seen)
                    repeats = repeats + 1 if step.outcome == "repeated" else 0
                    steps.append(step)
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": content})

            span.set_attributes({"stopReason": stopReason, "steps": len(steps), "usd": usd})
            return HarnessResult(None, stopReason, steps, usd, time.monotonic() - started)

    def exhaustedBudget(self, stepCount: int, usd: float, seconds: float) -> str | None:
        if stepCount >= self.budget.maxSteps:
            return "budgetSteps"
        if usd >= self.budget.maxUsd:
            return "budgetUsd"
        if seconds >= self.budget.maxSeconds:
            return "budgetSeconds"
        return None

    async def execute(self, call: ToolCall, stepNumber: int, seen: dict[str, str]) -> tuple[str, HarnessStep]:
        tool = self.tools.get(call.name)
        if tool is None:
            note = f"unknown tool {call.name!r}; available: {', '.join(self.tools)}"
            return f"error: {note}", HarnessStep(stepNumber, call.name, {}, "error", note)
        try:
            arguments = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as error:
            return f"error: arguments were not valid JSON ({error})", HarnessStep(stepNumber, call.name, {}, "error", "bad JSON")

        key = f"{call.name}:{json.dumps(arguments, sort_keys=True)}"
        if key in seen:
            # Not executed again: the model already has this result.
            note = "same call as before; use that result or try something different"
            return f"{note}. Earlier result: {seen[key][:800]}", HarnessStep(stepNumber, call.name, arguments, "repeated", note)

        if self.onToolCall:
            await self.onToolCall(call.name, arguments)
        with Tracer.span(f"harness.tool.{call.name}", step=stepNumber) as span:
            try:
                result = await tool.run(arguments)
            except ToolRefused as refusal:
                span.set_attribute("outcome", "refused")
                return f"refused: {refusal}", HarnessStep(stepNumber, call.name, arguments, "refused", str(refusal)[:300])
        content = json.dumps(result, default=str)
        if len(content) > tool.maxResultChars:
            content = content[: tool.maxResultChars] + f"... [truncated {len(content) - tool.maxResultChars} characters]"
        seen[key] = content
        return content, HarnessStep(stepNumber, call.name, arguments, "ok", tool.digest(result))

    def parseFinish(self, call: ToolCall) -> tuple[dict[str, Any] | None, str]:
        try:
            output = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as error:
            return None, f"finish arguments were not valid JSON ({error})"
        missing = [name for name in self.finishSchema.get("required", []) if name not in output]
        if missing:
            return None, f"finish is missing {missing}"
        return output, ""

    def compact(self, messages: list[dict[str, Any]]) -> None:
        """Replaces the oldest tool results with short digests while the context is over budget. The last two stay whole."""
        toolMessages = [message for message in messages if message["role"] == "tool"]
        for message in toolMessages[:-2]:
            if sum(len(str(item.get("content") or "")) for item in messages) <= self.contextChars:
                return
            if not str(message["content"]).startswith("[compacted]"):
                message["content"] = f"[compacted] {str(message['content'])[:300]}"
