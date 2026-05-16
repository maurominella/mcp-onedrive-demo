"""
MCP server that exposes a OneDrive tool using OBO (On-Behalf-Of) flow.

How it works:
1. Foundry calls this server via HTTP with Authorization: Bearer <user-token>
   The user token has audience api://<CLIENT_ID> (our app registration).
2. A Starlette middleware extracts the token from the Authorization header
   and stores it in a ContextVar, making it available to tool handlers.
3. The tool performs OBO: exchanges the user token for a Graph token via MSAL.
4. It calls Graph /me/drive/root/children with the Graph token.
5. Returns folder names and sizes — proving identity was the user's, not the app's.
"""

import contextvars
import os
import logging
import msal
import requests as http_requests

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings
from auth import _decode_jwt_claims

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CLIENT_ID = os.environ["MCP_CLIENT_ID"]
CLIENT_SECRET = os.environ["MCP_CLIENT_SECRET"]
TENANT_ID = os.environ["MCP_TENANT_ID"]

# ContextVar populated by the middleware for each incoming request
_incoming_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_incoming_token", default=None
)

class TokenExtractMiddleware:
    """ASGI middleware that extracts the Bearer token from each request
    and stores it in a ContextVar so tool handlers can access it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            token = auth[7:] if auth.startswith("Bearer ") else None
            _incoming_token.set(token)
        await self.app(scope, receive, send)


def _get_bearer_token() -> str | None:
    """Return the Bearer token stored by TokenExtractMiddleware for this request."""
    return _incoming_token.get()


def _obo_exchange(user_token: str) -> str:
    """Exchange the user token (audience=our app) for a Graph token via OBO."""
    app = msal.ConfidentialClientApplication(
        client_id=CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{TENANT_ID}",
    )
    result = app.acquire_token_on_behalf_of(
        user_assertion=user_token,
        scopes=["https://graph.microsoft.com/Files.Read"],
    )
    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "unknown"))
        raise RuntimeError(f"OBO exchange failed: {error}")
    return result["access_token"]


mcp = FastMCP(
    "onedrive-demo",
    stateless_http=True,
    transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)


@mcp.tool()
def get_onedrive_root_folders() -> list[dict]:
    """
    Returns the name and size (in bytes) of all items at the root of the
    authenticated user's OneDrive. Requires OBO to work — will fail if called
    with an app-only token.
    """
    user_token = _get_bearer_token()
    if not user_token:
        raise RuntimeError("No Bearer token found in request — cannot perform OBO")

    # Log the user identity from the incoming token (no extra Graph call needed)
    identity = _decode_jwt_claims(user_token)
    logger.info("Incoming token identity: %s", identity.get("preferred_username") or identity.get("oid"))

    logger.info("Performing OBO exchange...")
    graph_token = _obo_exchange(user_token)
    logger.info("OBO exchange successful. Calling Graph API...")

    resp = http_requests.get(
        "https://graph.microsoft.com/v1.0/me/drive/root/children"
        "?$select=name,size,folder&$top=50",
        headers={"Authorization": f"Bearer {graph_token}"},
        timeout=10,
    )
    resp.raise_for_status()
    items = resp.json().get("value", [])
    return [
        {"name": item["name"], "size_bytes": item.get("size", 0), "is_folder": "folder" in item}
        for item in items
    ]


if __name__ == "__main__":
    import uvicorn

    asgi_app = TokenExtractMiddleware(mcp.streamable_http_app())
    uvicorn.run(asgi_app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")