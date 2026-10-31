from urllib.parse import urlparse

from mcp.server.transport_security import TransportSecuritySettings


class McpTransport:
    """Keeps the MCP SDK's DNS-rebinding protection on, while accepting the server's own name (e.g. gateway:8100).

    The SDK only allows localhost by default, which would refuse every call between containers.
    """

    @staticmethod
    def security(url: str) -> TransportSecuritySettings:
        hostname = urlparse(url).hostname or "localhost"
        hosts = dict.fromkeys([hostname, "localhost", "127.0.0.1"])
        return TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[f"{host}:*" for host in hosts],
            allowed_origins=[f"http://{host}:*" for host in hosts],
        )
