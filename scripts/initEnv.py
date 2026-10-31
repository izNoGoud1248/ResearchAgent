import base64
import secrets
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat


class EnvInitializer:
    generated = (
        "REDIS_PASSWORD",
        "POSTGRES_PASSWORD",
        "AGENT_SIGNING_SEED",
        "SEARCH_HMAC_KEY",
        "NOTES_HMAC_KEY",
        "EVIL_HMAC_KEY",
        "LIBRARY_HMAC_KEY",
        "FACTCHECKER_SIGNING_SEED",
        "USER_API_KEY",
        "APPROVER_API_KEY",
        "SESSION_SECRET",
    )
    publicKeys = {"AGENT_PUBLIC_KEY": "AGENT_SIGNING_SEED", "FACTCHECKER_PUBLIC_KEY": "FACTCHECKER_SIGNING_SEED"}

    def __init__(self, root: Path):
        self.example = root / ".env.example"
        self.target = root / ".env"

    def run(self) -> list[str]:
        existing = self.read(self.target) if self.target.exists() else {}
        exampleLines = self.example.read_text().splitlines()
        merged = {**self.read(self.example), **existing}

        filled = []
        for name in self.generated:
            if not merged.get(name):
                merged[name] = self.newSecret(name)
                filled.append(name)
        for publicName, seedName in self.publicKeys.items():
            merged[publicName] = self.publicKeyFor(merged[seedName])

        written = set()
        lines = []
        for line in exampleLines:
            name = line.split("=", 1)[0]
            if "=" in line and not line.startswith("#"):
                lines.append(f"{name}={merged[name]}")
                written.add(name)
            else:
                lines.append(line)
        lines += [f"{name}={value}" for name, value in existing.items() if name not in written]

        self.target.write_text("\n".join(lines) + "\n")
        return filled

    @staticmethod
    def read(path: Path) -> dict[str, str]:
        values = {}
        for line in path.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip()
        return values

    @staticmethod
    def newSecret(name: str) -> str:
        if name.endswith("_SIGNING_SEED"):
            return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()
        return secrets.token_urlsafe(32)

    @staticmethod
    def publicKeyFor(seed: str) -> str:
        privateKey = Ed25519PrivateKey.from_private_bytes(base64.urlsafe_b64decode(seed))
        raw = privateKey.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        return base64.urlsafe_b64encode(raw).decode()


if __name__ == "__main__":
    filled = EnvInitializer(Path(__file__).resolve().parent.parent).run()
    print("generated: " + ", ".join(filled) if filled else "nothing new to generate")
