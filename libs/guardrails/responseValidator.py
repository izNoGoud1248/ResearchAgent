import hashlib
import hmac
import json
import re
from collections.abc import Iterator
from typing import Any

from libs.guardrails.inputGuard import InputGuard
from libs.guardrails.verdict import Verdict


class ResponseSigner:
    def __init__(self, key: bytes):
        self.key = key

    @staticmethod
    def canonical(payload: Any) -> bytes:
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

    def sign(self, payload: Any) -> str:
        return hmac.new(self.key, self.canonical(payload), hashlib.sha256).hexdigest()


class ResponseValidator:
    hiddenTags = re.compile("[\U000e0000-\U000e007f]")

    poisonPatterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"<\s*(important|instructions?|system)\s*>",
            r"\b(call|invoke|use|run)\s+the\s+[\w.]+\s+tool\b",
            r"\b(send|post|upload|forward|exfiltrate)\b.{0,40}\bhttps?://",
            r"\bdo not (tell|inform|mention|show)\b.{0,30}\buser\b",
        )
    ]

    def __init__(self, keys: dict[str, bytes], guard: InputGuard | None = None, maxBytes: int = 200000):
        self.keys = keys
        self.guard = guard or InputGuard()
        self.maxBytes = maxBytes

    neutralized = "[removed: instruction-like text]"

    def validate(self, server: str, payload: Any, signature: str) -> Verdict:
        verdict = self.verifySignature(server, payload, signature)
        if not verdict.allowed:
            return verdict
        for text in self.strings(payload):
            poison = self.findPoison(text)
            if poison:
                return Verdict.deny(f"poisoned content: {poison!r}")
        return Verdict.allow()

    def verifySignature(self, server: str, payload: Any, signature: str) -> Verdict:
        key = self.keys.get(server)
        if key is None:
            return Verdict.deny(f"unknown tool server {server!r}")
        body = ResponseSigner.canonical(payload)
        if len(body) > self.maxBytes:
            return Verdict.deny(f"response larger than {self.maxBytes} bytes")
        expected = hmac.new(key, body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return Verdict.deny("signature does not match")
        return Verdict.allow()

    def neutralize(self, value: Any) -> tuple[Any, int]:
        """For document text (papers), where quoting an attack is legitimate: remove instruction-like spans
        instead of rejecting the whole response. Returns the cleaned value and how many spans were removed."""
        if isinstance(value, str):
            cleaned, removed = self.hiddenTags.subn("", value)
            for pattern in [*self.poisonPatterns, *self.guard.injectionPatterns]:
                cleaned, count = pattern.subn(self.neutralized, cleaned)
                removed += count
            return cleaned, removed
        if isinstance(value, dict):
            pairs = {key: self.neutralize(item) for key, item in value.items()}
            return {key: item for key, (item, _) in pairs.items()}, sum(count for _, count in pairs.values())
        if isinstance(value, list):
            pairs = [self.neutralize(item) for item in value]
            return [item for item, _ in pairs], sum(count for _, count in pairs)
        return value, 0

    def findPoison(self, text: str) -> str | None:
        if self.hiddenTags.search(text):
            return "hidden unicode tag characters"
        for pattern in self.poisonPatterns:
            match = pattern.search(text)
            if match:
                return match.group(0)
        return self.guard.findInjection(text)

    def strings(self, value: Any) -> Iterator[str]:
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for item in value.values():
                yield from self.strings(item)
        elif isinstance(value, list):
            for item in value:
                yield from self.strings(item)
