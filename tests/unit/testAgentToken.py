import os

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from libs.guardrails.agentToken import AgentTokenIssuer, AgentTokenVerifier
from libs.settings import Settings


class TestAgentToken:
    @staticmethod
    def publicKeyFor(seed: bytes) -> bytes:
        return Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)

    def testRoundTripWithKeysFromEnv(self, settings: Settings):
        issuer = AgentTokenIssuer(Settings.decodeKey(settings.agentSigningSeed.get_secret_value()))
        verifier = AgentTokenVerifier({"orchestrator": Settings.decodeKey(settings.agentPublicKey)})
        claims = verifier.verify(issuer.issue("researcher", "run1", "trace1"))
        assert (claims.agent, claims.issuer, claims.runId, claims.traceId) == ("researcher", "orchestrator", "run1", "trace1")

    def testRejectsExpiredToken(self):
        seed = os.urandom(32)
        token = AgentTokenIssuer(seed, lifetime=-1).issue("researcher", "run1", "trace1")
        with pytest.raises(jwt.ExpiredSignatureError):
            AgentTokenVerifier({"orchestrator": self.publicKeyFor(seed)}).verify(token)

    def testRejectsTokenSignedByOtherKey(self):
        token = AgentTokenIssuer(os.urandom(32)).issue("writer", "run1", "trace1")
        with pytest.raises(jwt.InvalidSignatureError):
            AgentTokenVerifier({"orchestrator": self.publicKeyFor(os.urandom(32))}).verify(token)

    def testRejectsUntrustedIssuer(self):
        seed = os.urandom(32)
        token = AgentTokenIssuer(seed, issuer="stranger").issue("writer", "run1", "trace1")
        with pytest.raises(jwt.InvalidIssuerError):
            AgentTokenVerifier({"orchestrator": self.publicKeyFor(seed)}).verify(token)

    def testRejectsTamperedClaims(self):
        seed = os.urandom(32)
        header, body, signature = AgentTokenIssuer(seed).issue("researcher", "run1", "trace1").split(".")
        otherBody = AgentTokenIssuer(seed).issue("writer", "run1", "trace1").split(".")[1]
        with pytest.raises(jwt.InvalidSignatureError):
            AgentTokenVerifier({"orchestrator": self.publicKeyFor(seed)}).verify(f"{header}.{otherBody}.{signature}")
