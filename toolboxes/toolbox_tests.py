import os
import re
from monitoring import logger
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPToolboxTool, ToolSearchToolboxTool, WebSearchToolboxTool
import asyncio

# Constants and Variables
PROJECT_ENDPOINT = os.environ.get("TOOLBOX_PROJECT_ENDPOINT").rstrip("/")
MCP_TOOL_NAME = os.environ.get("MCP_TOOL_NAME")
TOOLBOX_NAME = os.environ.get("TOOLBOX_NAME")
TOOLBOX_DESCRIPTION = os.environ.get("TOOLBOX_DESCRIPTION")
TOOL_CONNECTION_NAME = os.environ.get("TOOL_CONNECTION_NAME")
PROJECT_CONNECTION_ID = f"{os.environ.get("TOOLBOX_PROJECT_RESOURCE_ID")}/connections/{TOOL_CONNECTION_NAME}"
MCP_TOOL_ENDPOINT = f"{os.environ.get('MCP_ACA_ENDPOINT')}/mcp"

CREATE_TOOLBOX_EVEN_IF_EXISTS = False
# The project connection created in Foundry or via CLI establishes how to authenticate to the MCP server.

# The MCPToolboxTool definition establishes where and how the server appears in the toolbox:
onedrive_mcp_tool = MCPToolboxTool(
    server_label=MCP_TOOL_NAME,
    server_url=MCP_TOOL_ENDPOINT,
    require_approval="never",
    project_connection_id=TOOL_CONNECTION_NAME,
)

# Create Foundry project client
foundry_project_client = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)

def retrieve_existing_toolbox(toolbox_name: str):
    if toolbox_name not in [t["name"] for t in foundry_project_client.toolboxes.list()]:
        print(f"No existing toolbox found with name: {toolbox_name}")
        return None
    else:
        existing_toolbox = foundry_project_client.toolboxes.get(toolbox_name)
        existing_toolbox_versions = list(foundry_project_client.toolboxes.list_versions(toolbox_name))

        # use created_at to determine the latest version if needed
        existing_toolbox_versions.sort(key=lambda v: v.created_at)

        # retrieve the latest created version based on the sorted list and extract the date
        latest_toolbox_version = existing_toolbox_versions[-1] if existing_toolbox_versions else None
        print(
            f"Found existing toolbox: {existing_toolbox.name}, "
            f"default version: {existing_toolbox.default_version}, "
            f"latest created version: {latest_toolbox_version.version if latest_toolbox_version else 'N/A'}, "
            f"latest created at: {latest_toolbox_version.created_at if latest_toolbox_version else 'N/A'}"
            )
        return latest_toolbox_version


toolbox_version = retrieve_existing_toolbox(TOOLBOX_NAME)

if toolbox_version is not None and not CREATE_TOOLBOX_EVEN_IF_EXISTS:
    print(f"Latest toolbox version is {toolbox_version.version}, so we do not create a new one as requested.")
else:
    if toolbox_version is not None and CREATE_TOOLBOX_EVEN_IF_EXISTS:
        print(f"Latest toolbox version is {toolbox_version.version}, but we create a new one as requested.")
    else:  
        print("No existing toolbox found, so we create a new one as requested.")

    # Create toolbox version with web search and MCP tools
    toolbox_version = foundry_project_client.toolboxes.create_version(
        name=TOOLBOX_NAME,
        description=TOOLBOX_DESCRIPTION,
        tools=[
            # WebSearchToolboxTool(),
            onedrive_mcp_tool,
            ToolSearchToolboxTool(),
        ],
    )
    print(f"Created toolbox: {toolbox_version.name}, version: {toolbox_version.version}")

toolbox_developer_url = (
    f"{PROJECT_ENDPOINT}/toolboxes/{toolbox_version.name}"
    f"/versions/{toolbox_version.version}/mcp?api-version=v1"
)
toolbox_consumer_url = (
    f"{PROJECT_ENDPOINT}/toolboxes/{toolbox_version.name}/mcp?api-version=v1"
)

print(f"Toolbox developer URL: {toolbox_developer_url}")
print(f"Toolbox consumer URL: {toolbox_consumer_url}")


def authorization_headers() -> dict:
    token = DefaultAzureCredential().get_token("https://ai.azure.com/.default").token
    return {
        "Authorization": f"Bearer {token}"
    }


def find_consent_url(error: BaseException) -> str | None:
    if isinstance(error, BaseExceptionGroup):
        for nested_error in error.exceptions:
            if consent_url := find_consent_url(nested_error):
                return consent_url

    message = str(error)
    if "CONSENT_REQUIRED" in message:
        match = re.search(r'https://[^\s"<>]+', message)
        if match:
            return match.group(0)

    return None


# Connect to the toolbox and list tools
async def verify_toolbox(toolbox_url: str, headers: dict):
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    try:
        async with httpx2.AsyncClient(headers=headers) as http_client:
            async with streamable_http_client(
                toolbox_url,
                http_client=http_client,
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()

                    # List available tools
                    tools_result = await session.list_tools()
                    print(f"Tools found: {len(tools_result.tools)}")
                    for tool in tools_result.tools:
                        print(f"  - {tool.name}: {(tool.description or '')}")
    except Exception as error:
        consent_url = find_consent_url(error)
        if not consent_url:
            raise

        print("OAuth consent is required. Open this URL, authorize access, then run again:")
        print(consent_url)

asyncio.run(verify_toolbox(
    toolbox_url=toolbox_developer_url, 
    headers=authorization_headers()))


print ("Program ends here.")