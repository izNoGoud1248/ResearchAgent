import hashlib
import hmac
import time

from fastapi import HTTPException, Request, Response

from libs.settings import Settings


class SessionCookie:
    """A signed browser session: role and expiry, sealed with HMAC. The API key itself never reaches JavaScript."""

    name = "researchdeskSession"

    def __init__(self, secret: bytes, lifetime: int = 12 * 3600, secure: bool = False):
        self.secret = secret
        self.lifetime = lifetime
        self.secure = secure

    def seal(self, role: str) -> str:
        body = f"{role}.{int(time.time()) + self.lifetime}"
        return f"{body}.{self.signature(body)}"

    def open(self, value: str) -> str | None:
        """Returns the role, or None for anything tampered with or expired."""
        body, _, signature = value.rpartition(".")
        role, _, expiry = body.partition(".")
        if not hmac.compare_digest(signature, self.signature(body)) or not expiry.isdigit() or int(expiry) < time.time():
            return None
        return role

    def signature(self, body: str) -> str:
        return hmac.new(self.secret, body.encode(), hashlib.sha256).hexdigest()

    def attach(self, response: Response, role: str) -> None:
        response.set_cookie(
            self.name, self.seal(role), max_age=self.lifetime, httponly=True, samesite="strict", secure=self.secure, path="/"
        )

    def clear(self, response: Response) -> None:
        response.delete_cookie(self.name, path="/", httponly=True, samesite="strict", secure=self.secure)


class ApiAuth:
    """API keys with two roles; browsers use a session cookie instead. An approver can do everything a user can."""

    roles = ("user", "approver")

    def __init__(self, settings: Settings):
        self.keys = {
            "user": settings.userApiKey.get_secret_value(),
            "approver": settings.approverApiKey.get_secret_value(),
        }
        self.sessions = SessionCookie(settings.sessionSecret.get_secret_value().encode(), secure=settings.cookieSecure)

    def roleForKey(self, presented: str) -> str | None:
        for role, key in self.keys.items():
            if presented and hmac.compare_digest(presented, key):
                return role
        return None

    def roleFor(self, request: Request) -> str:
        role = self.roleForKey(request.headers.get("x-api-key", ""))
        if role is None and (cookie := request.cookies.get(SessionCookie.name)):
            role = self.sessions.open(cookie)
        if role not in self.roles:
            raise HTTPException(status_code=401, detail="missing or unknown API key")
        return role

    def require(self, request: Request, role: str) -> str:
        actual = self.roleFor(request)
        if role == "approver" and actual != "approver":
            raise HTTPException(status_code=403, detail="approver role required")
        return actual
