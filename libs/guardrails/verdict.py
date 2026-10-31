from dataclasses import dataclass


@dataclass(frozen=True)
class Verdict:
    allowed: bool
    reason: str = ""

    @classmethod
    def allow(cls) -> "Verdict":
        return cls(True)

    @classmethod
    def deny(cls, reason: str) -> "Verdict":
        return cls(False, reason)
