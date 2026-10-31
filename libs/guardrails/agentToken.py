import time
import uuid
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


@dataclass(frozen=True)
class AgentClaims:
    agent: str
    issuer: str
    runId: str
    traceId: str


class AgentTokenIssuer:
    def __init__(self, seed: bytes, issuer: str = "orchestrator", lifetime: int = 300):
        self.privateKey = Ed25519PrivateKey.from_private_bytes(seed)
        self.issuer = issuer
        self.lifetime = lifetime

    def issue(self, agent: str, runId: str, traceId: str, audience: str = "mcpGateway") -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "aud": audience,
            "sub": agent,
            "runId": runId,
            "traceId": traceId,
            "iat": now,
            "exp": now + self.lifetime,
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(claims, self.privateKey, algorithm="EdDSA")


class AgentTokenVerifier:
    """Accepts only tokens signed by a trusted issuer and addressed to this service's audience."""

    def __init__(self, trustedIssuers: dict[str, bytes], audience: str = "mcpGateway"):
        self.publicKeys = {name: Ed25519PublicKey.from_public_bytes(key) for name, key in trustedIssuers.items()}
        self.audience = audience

    def verify(self, token: str) -> AgentClaims:
        """Raises jwt.InvalidTokenError (or a subclass) for anything not signed by a trusted issuer."""
        issuer = jwt.decode(token, options={"verify_signature": False}).get("iss")
        publicKey = self.publicKeys.get(issuer)
        if publicKey is None:
            raise jwt.InvalidIssuerError(f"untrusted issuer {issuer!r}")
        claims = jwt.decode(
            token,
            publicKey,
            algorithms=["EdDSA"],
            audience=self.audience,
            issuer=issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
        return AgentClaims(claims["sub"], issuer, claims["runId"], claims["traceId"])
