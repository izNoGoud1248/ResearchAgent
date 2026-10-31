import json
from typing import Any


class JsonReply:
    """Model output is untrusted text even in JSON mode, so parsing never raises."""

    @staticmethod
    def parse(text: str) -> dict[str, Any]:
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}
