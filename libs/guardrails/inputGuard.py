import re
import unicodedata

from libs.guardrails.verdict import Verdict


class InputGuard:
    # Zero-width characters and Unicode tag characters, used to hide instructions from humans.
    hiddenCharacters = re.compile("[​-‏⁠-⁤﻿\U000e0000-\U000e007f]")

    injectionPatterns = [
        re.compile(pattern, re.IGNORECASE)
        for pattern in (
            r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|earlier|all|your)\b.{0,40}\b(instructions?|prompts?|rules|guidelines)\b",
            r"\byou are now\b",
            r"\b(reveal|print|show|repeat|leak)\b.{0,30}\b(system|hidden|initial)\s+(prompt|instructions?|message)\b",
            r"\b(developer|god|jailbreak|dan)\s+mode\b",
            r"\bdo anything now\b",
            r"<\s*/?\s*(system|assistant|im_start|im_end)\s*>",
            r"\bact as\b.{0,30}\b(unrestricted|unfiltered|jailbroken)\b",
            r"\bnew instructions?\s*:",
        )
    ]

    def __init__(self, maxLength: int = 2000):
        self.maxLength = maxLength

    def normalize(self, text: str) -> str:
        return self.hiddenCharacters.sub("", unicodedata.normalize("NFKC", text))

    def findInjection(self, text: str) -> str | None:
        cleanText = self.normalize(text)
        for pattern in self.injectionPatterns:
            match = pattern.search(cleanText)
            if match:
                return match.group(0)
        return None

    def checkMessage(self, text: str) -> Verdict:
        cleanText = self.normalize(text).strip()
        if not cleanText:
            return Verdict.deny("empty message")
        if len(cleanText) > self.maxLength:
            return Verdict.deny(f"message longer than {self.maxLength} characters")
        injection = self.findInjection(cleanText)
        if injection:
            return Verdict.deny(f"possible prompt injection: {injection!r}")
        return Verdict.allow()
