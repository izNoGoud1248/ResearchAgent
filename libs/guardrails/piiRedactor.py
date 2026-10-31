import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Redaction:
    value: Any
    found: dict[str, int] = field(default_factory=dict)


class PiiRedactor:
    # Order matters: cards are matched before phones so a card is not half-redacted as a phone.
    patterns = {
        "email": re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"),
        "apiKey": re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_-]{20,}"),
        "card": re.compile(r"\b(?:\d[ -]?){12,18}\d\b"),
        "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "phone": re.compile(r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\w)"),
        "ipAddress": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    }

    def redact(self, value: Any) -> Redaction:
        found: dict[str, int] = {}
        return Redaction(self.walk(value, found), found)

    def walk(self, value: Any, found: dict[str, int]) -> Any:
        if isinstance(value, str):
            return self.redactText(value, found)
        if isinstance(value, dict):
            return {key: self.walk(item, found) for key, item in value.items()}
        if isinstance(value, list):
            return [self.walk(item, found) for item in value]
        return value

    def redactText(self, text: str, found: dict[str, int]) -> str:
        for kind, pattern in self.patterns.items():
            text = pattern.sub(lambda match: self.replace(kind, match.group(0), found), text)
        return text

    def replace(self, kind: str, text: str, found: dict[str, int]) -> str:
        if kind == "card" and not self.passesLuhn(text):
            return text
        if kind == "ipAddress" and any(int(part) > 255 for part in text.split(".")):
            return text
        found[kind] = found.get(kind, 0) + 1
        return f"[REDACTED:{kind}]"

    @staticmethod
    def passesLuhn(text: str) -> bool:
        total = 0
        for index, digit in enumerate(reversed([int(char) for char in text if char.isdigit()])):
            if index % 2 == 1:
                digit = digit * 2 - 9 if digit > 4 else digit * 2
            total += digit
        return total % 10 == 0
