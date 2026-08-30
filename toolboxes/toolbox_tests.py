import os
import re
from monitoring import logger
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPToolboxTool, ToolSearchToolboxTool, WebSearchToolboxTool
import asyncio

# Constants and Variables
PROJECT_ENDPOINT = os.environ.get("TOOLBOX_PROJECT_ENDPOINT")
TOOL_CONNECTION_NAME = "mcp-onedrive-demo01"
PROJECT_CONNECTION_ID = f"{os.environ.get("TOOLBOX_PROJECT_RESOURCE_ID")}/connections/{TOOL_CONNECTION_NAME}"
MCP_TOOL_NAME = os.environ.get("MCP_TOOL_NAME")
MCP_TOOL_ENDPOINT = f"{os.environ.get('MCP_ACA_ENDPOINT')}/mcp"
TOOLBOX_NAME = "mm_toolbox_for_onedrive"
TOOLBOX_DESCRIPTION = "Toolbox with the OneDrive MCP tool"
# The project connection created in Foundry or via CLI establishes how to authenticate to the MCP server.

# The MCPToolboxTool definition establishes where and how the server appears in the toolbox:
onedrive_mcp_tool = MCPToolboxTool(
    server_label=MCP_TOOL_NAME,
    server_url=MCP_TOOL_ENDPOINT,
    require_approval="never",
    project_connection_id=TOOL_CONNECTION_NAME,
)

# Create Foundry project client
project = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)


# Create toolbox version with web search and MCP tools
toolbox_version = project.toolboxes.create_version(
    name=TOOLBOX_NAME,
    description=TOOLBOX_DESCRIPTION,
    tools=[
        # WebSearchToolboxTool(),
        onedrive_mcp_tool,
        ToolSearchToolboxTool(),
    ],
)
print(f"Created toolbox: {toolbox_version.name}, version: {toolbox_version.version}")

project_endpoint = PROJECT_ENDPOINT.rstrip("/")
toolbox_developer_url = (
    f"{project_endpoint}/toolboxes/{toolbox_version.name}"
    f"/versions/{toolbox_version.version}/mcp?api-version=v1"
)
toolbox_consumer_url = (
    f"{project_endpoint}/toolboxes/{toolbox_version.name}/mcp?api-version=v1"
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
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    try:
        async with streamablehttp_client(
            toolbox_url,
            headers=headers,
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()

                # List available tools
                tools_result = await session.list_tools()
                print(f"Tools found: {len(tools_result.tools)}")
                for tool in tools_result.tools:
                    print(f"  - {tool.name}: {(tool.description or '')[:80]}")
    except Exception as error:
        consent_url = find_consent_url(error)
        if not consent_url:
            raise

        print("OAuth consent is required. Open this URL, authorize access, then run again:")
        print(consent_url)

asyncio.run(verify_toolbox(
    toolbox_url=toolbox_developer_url, 
    headers=authorization_headers()))

# Run a local Agent Framework agent through the Foundry Toolbox.
async def run_agent_with_toolbox(toolbox_url: str, chat_client, prompt: str):
    from agent_framework import Agent, MCPStreamableHTTPTool

    toolbox_tool = MCPStreamableHTTPTool(
        name=TOOLBOX_NAME,
        url=toolbox_url,
        description=TOOLBOX_DESCRIPTION,
        load_prompts=False,
        header_provider=lambda _: authorization_headers(),
    )

    async with toolbox_tool:
        agent = Agent(
            client=chat_client,
            name="onedrive-toolbox-agent",
            instructions="Use the Foundry Toolbox tools when relevant.",
            tools=[toolbox_tool],
        )
        return await agent.run(prompt)


print ("Program ends here.")