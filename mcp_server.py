"""
MCP server that exposes a OneDrive tool using OBO (On-Behalf-Of) flow.

How it works:
1. Foundry calls this server via HTTP with Authorization: Bearer <authorization-token>
   The authorization token has audience api://<CLIENT_ID> (our app registration).
2. A Starlette middleware extracts the token from the Authorization header
   and stores it in a ContextVar, making it available to tool handlers.
3. The tool performs OBO: exchanges the authorization token for a Graph token via MSAL.
4. It calls Graph /me/drive/root/children with the Graph token.
5. Returns folder names and sizes — proving identity was the user's, not the app's.
"""

import os
from dotenv import load_dotenv
load_dotenv()  # MUST be first: env vars must be set before any import reads them

# --- Azure Monitor setup ---------------------------------------------------
# We call configure_azure_monitor() OURSELVES first (with default INFO+ logging)
# because agent_framework also calls it internally during import — but at WARNING level,
# which would prevent our logger.info() traces from reaching App Insights.
# The double call causes OTel to emit two harmless startup warnings:
#   "Overriding of current LoggerProvider is not allowed"
#   "Overriding of current TracerProvider is not allowed"
# These are cosmetic only: they fire once at startup, do not affect runtime behaviour,
# and are not worth working around with extra complexity.

if os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor
    configure_azure_monitor(logging_level=logging.INFO)  # capture INFO+ in App Insights (default is WARNING)

import contextvars, json, logging
import msal
import requests as http_requests

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from auth import _decode_jwt_claims

# --------------------------------------------------------------------------
# Configure logging - WARNING for everything else, while INFO for this module only
logging.basicConfig(level=logging.WARNING) # this is the "father" logger, set to WARNING to avoid too much noise from other modules
logger = logging.getLogger(__name__) # this is the "child" logger for our module (this module)
logger.setLevel(logging.INFO) # we set the child logger to INFO to get more detailed logs from our module
if not logger.handlers: # avoid adding multiple handlers if this code is reloaded multiple times (e.g. during development)
    _handler = logging.StreamHandler()
    _handler.setLevel(logging.INFO)
    logger.addHandler(_handler)
    logger.propagate = True # (default) so logs also reach the root logger

# --------------------------------------------------------------------------

MCP_CLIENT_ID = os.environ["MCP_CLIENT_ID"]
MCP_CLIENT_SECRET = os.environ["MCP_CLIENT_SECRET"]
MCP_TENANT_ID = os.environ["MCP_TENANT_ID"]
TARGET_SCOPES = json.loads(os.environ["TARGET_SCOPES"])

# ContextVar populated by the middleware for each incoming request
# This is just the internal name of ContextVar, used for debug and introspection. 
# It does not have any effect on the stored value or the scoping behavior.
# Takeaway: used just to give a readable name to the variable in tracing, for example when Python shows the ContextVar in logs or debugging tools.
# ContextVar("nome") stores that name for identification.
# It's not a lookup key, it's not used to retrieve the value.
# The actual value is what we set with .set() and retrieve with .get().
_authorization_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "_authorization_token", default=None
)

class TokenExtractMiddleware:
    """ASGI middleware that extracts the Bearer token from each requestperò per poter
    and stores it in a ContextVar so tool handlers can access it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            x_ms_user_token = headers.get(b"x-ms-user-token", b"").decode() # just for testing
            logger.info(f"x_ms_user_token: {x_ms_user_token}") # just for testing
            auth_header = headers.get(b"authorization", b"").decode()
            authorization_token = auth_header[7:] if auth_header.startswith("Bearer ") else None
            _authorization_token.set(authorization_token)
        await self.app(scope, receive, send)


def _get_authorization_token() -> str | None:
    """Return the Bearer token stored by TokenExtractMiddleware for this request."""
    return _authorization_token.get()


def _obo_exchange(user_token: str, target_scopes: list[str]) -> str:
    """Exchange the user token (audience=our app) for a Graph token via OBO."""

    app = msal.ConfidentialClientApplication(
        client_id=MCP_CLIENT_ID,
        client_credential=MCP_CLIENT_SECRET,
        authority=f"https://login.microsoftonline.com/{MCP_TENANT_ID}",
    )

    result = app.acquire_token_on_behalf_of(
        user_assertion=user_token,
        scopes=target_scopes,
    )

    if "access_token" not in result:
        error = result.get("error_description", result.get("error", "unknown"))
        raise RuntimeError(f"OBO exchange failed: {error}")

    return result["access_token"]

def _validate_token_audience(token: str) -> bool:
    """
    Check that the token has the expected audience and scope for our app.
    This is a sanity check to provide clearer errors when the token is not what we expect 
    (e.g. an app-only token instead of a user token).
    """

    claims = _decode_jwt_claims(token)
    aud = claims.get("aud")
    scp = claims.get("scp")
    logger.info("Validating token audience. aud: %s, scp: %s", aud, scp)
    return (not aud) or (not scp) == False
    

###################################################################################################
mcp = MCPServer("onedrive-demo")

###################################################################################################
@mcp.tool()
def get_onedrive_root_folders() -> list[dict]:
    """
    Returns the name and size (in bytes) of all items at the root of the
    authenticated user's OneDrive. Requires OBO to work — will fail if called
    with an app-only token.
    """
    authorization_token = _get_authorization_token()
    if not authorization_token:
        raise RuntimeError("No Authorization token found in request — cannot perform OBO")

    # Log the user identity from the incoming token (no extra Graph call needed)
    identity = _decode_jwt_claims(authorization_token)
    logger.info("Incoming token identity: %s", identity.get("name") or identity.get("oid"))

    logger.info("Performing OBO exchange...")
    graph_token = _obo_exchange(authorization_token, TARGET_SCOPES)
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

@mcp.tool()
def WhoAmI() -> dict:
    """
    Returns the identity from the incoming token, without performing OBO.
    This will show the difference between user and app tokens: user tokens
    will contain username/email, while app tokens will not.
    """
    user_token = _get_authorization_token()
    if not user_token:
        raise RuntimeError("No Bearer token found in request")
    elif not _validate_token_audience(user_token):
        raise RuntimeError("Invalid token _validate_token_audience")
    
    identity = _decode_jwt_claims(user_token)

    logger.info("whoami tool called. Incoming token identity: %s", identity.get("preferred_username") or identity.get("oid"))
    return [
        {
            item[0]: item[1]
        }
        for item in identity.items()
    ]

@mcp.tool()
def create_ticket(description: str) -> dict:
    """
    Simulates the creation of a ticket in a service desk. It takes the user identity from the token and the input from the user, and returns a fake ticket.
    This is to show how you can use the user identity from the token to perform actions on behalf of the user.
    """
    user_token = _get_authorization_token()
    if not user_token:
        raise RuntimeError("No Bearer token found in request")
    elif not _validate_token_audience(user_token):
        raise RuntimeError("Invalid token audience or scope — expected api://<CLIENT_ID> with scope access_as_user")

    identity = _decode_jwt_claims(user_token)
    logger.info("create_ticket tool called. Incoming token identity: %s", identity.get("preferred_username") or identity.get("oid"))
    return {
        "ticket_id": len(description),
        "user": identity.get("name") or identity.get("oid"),
        "description": description
    }

if __name__ == "__main__":
    import uvicorn

    asgi_app = TokenExtractMiddleware(
        mcp.streamable_http_app(
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
    )
    uvicorn.run(asgi_app, host="0.0.0.0", port=8000, proxy_headers=True, forwarded_allow_ips="*")