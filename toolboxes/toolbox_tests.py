import os
from monitoring import logger
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import MCPTool, MCPToolboxTool, PromptAgentDefinition, ToolSearchToolboxTool
import re
import asyncio

# Constants and Variables
PROJECT_ENDPOINT = os.environ.get("PROJECT_ENDPOINT").rstrip("/")
TOOL01_NAME = os.environ.get("TOOL01_NAME")
TOOL01_CONNECTION_NAME = os.environ.get("TOOL01_CONNECTION_NAME")
TOOL01_ENDPOINT = os.environ.get('TOOL01_ENDPOINT')
TOOLBOX01_NAME = os.environ.get("TOOLBOX01_NAME")
TOOLBOX01_CONNECTION_NAME = os.environ.get("TOOLBOX01_CONNECTION_NAME")
TOOLBOX01_DESCRIPTION = os.environ.get("TOOLBOX01_DESCRIPTION")
TOOLBOX01_CONNECTION_ID = f"{os.environ.get("PROJECT_RESOURCE_ID")}/connections/{TOOLBOX01_CONNECTION_NAME}"

CREATE_TOOLBOX_EVEN_IF_EXISTS = False
# The project connection created in Foundry or via CLI establishes how to authenticate to the MCP server.

def check_existing_toolbox(foundry_project_client, toolbox_name: str):
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


def create_or_retrieve_toolbox(
        foundry_project_client,
        toolbox_name: str, 
        toolbox_description: str,
        tool,
        create_anyway: bool = False):
    
    toolbox_version = check_existing_toolbox(foundry_project_client, toolbox_name)

    if toolbox_version is not None and not create_anyway:
        print(f"Latest toolbox version is {toolbox_version.version}, so we do not create a new one as requested.")
    else:
        if toolbox_version is not None and create_anyway:
            print(f"Latest toolbox version is {toolbox_version.version}, but we create a new one as requested.")
        else:  
            print("No existing toolbox found, so we create a new one as requested.")

        # Create toolbox version with web search and MCP tools
        toolbox_version = foundry_project_client.toolboxes.create_version(
            name=toolbox_name,
            description=toolbox_description,
            tools=[
                # WebSearchToolboxTool(),
                tool,
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

    return toolbox_version, toolbox_developer_url, toolbox_consumer_url


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


async def list_toolbox_tools(toolbox_url: str, headers: dict) -> bool:
    # Connect to the toolbox and list tools
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    success = True

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
                    print(f"\nTools found: {len(tools_result.tools)}")
                    i = 1
                    for tool in tools_result.tools:
                        print(f"{i}. {tool.name}: {(tool.description or '')}")
                        i += 1

    except Exception as error:
        consent_url = find_consent_url(error)
        if not consent_url:
            raise

        print("\nOAuth consent is required. Open this URL, authorize access, then run again:")
        print(f"=====\n{consent_url}\n=====")
        success = False

    return success

    


# INSTRUCTIONS START HERE

# Create Foundry project client
foundry_project_client = AIProjectClient(
    endpoint=PROJECT_ENDPOINT,
    credential=DefaultAzureCredential(),
)

# MCPTool is used by a prompt agent to call the OneDrive MCP server directly.
agent_tool01 = MCPTool(
    server_label=TOOL01_NAME,
    server_url=TOOL01_ENDPOINT,
    require_approval="never",
    project_connection_id=TOOL01_CONNECTION_NAME,
)

agent = foundry_project_client.agents.create_version(
    agent_name=os.environ["AGENT_WITH_TOOL_NAME"],
    definition=PromptAgentDefinition(
        model="gpt-5.4-mini",#os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        instructions=(
            "You are a helpful assistant. "
            "Use the OneDrive toolbox whenever the request requires OneDrive data."
        ),
        tools=[agent_tool01],
    ),
)

# MCPToolboxTool is used only inside a toolbox definition.
# So this tool is only used within the toolbox and not directly by the prompt agent.
# In other words, I can't use the "normal" agent_tool01 as a tool inside the toolbox:
# I need a separate MCPToolboxTool instance, mapped specifically for the toolbox.
toolbox_tool01 = MCPToolboxTool(
    server_label=TOOL01_NAME,
    server_url=TOOL01_ENDPOINT,
    require_approval="never",
    project_connection_id=TOOL01_CONNECTION_NAME,
)


# toolbox is a ToolboxVersionObject Azure AI Projects SDK
toolbox, toolbox_developer_url, toolbox_consumer_url = create_or_retrieve_toolbox(
    foundry_project_client=foundry_project_client,
    toolbox_name=TOOLBOX01_NAME, 
    toolbox_description=TOOLBOX01_DESCRIPTION, 
    tool=toolbox_tool01,
    create_anyway=CREATE_TOOLBOX_EVEN_IF_EXISTS
    )

success = asyncio.run(list_toolbox_tools(
    toolbox_url=toolbox_developer_url, 
    headers=authorization_headers()))

if not success:
    print("Failed to list toolbox tools. Exiting.")
    exit(1)




# A prompt agent sees a toolbox through its MCP consumer endpoint, so this is an MCPTool.
agent_toolbox01 = MCPTool(
    server_label=toolbox.name,
    server_url=toolbox_consumer_url,
    require_approval="never",
    project_connection_id=TOOLBOX01_CONNECTION_NAME,
)

agent = foundry_project_client.agents.create_version(
    agent_name=os.environ["AGENT_WITH_TOOLBOX_NAME"],
    definition=PromptAgentDefinition(
        model="gpt-5.4-mini",#os.environ["AZURE_AI_MODEL_DEPLOYMENT_NAME"],
        instructions=(
            "You are a helpful assistant. "
            "Use the OneDrive toolbox whenever the request requires OneDrive data."
        ),
        tools=[agent_toolbox01],
    ),
)


print ("\nProgram ends here.")