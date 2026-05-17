# mcp-onedrive-demo
Authenticated MCP Server with OBO to read user's files from their OneDrive through MS Graph


## What this sample demonstrates

This sample demonstrates a **key advantage of code-based hosted agents**:

- **Local Python tool execution** - Run custom Python functions as agent tools

Code-based agents can execute **any Python code** you write. This sample includes a Seattle Hotel Agent with a `get_available_hotels` tool that searches for available hotels based on check-in/check-out dates and budget preferences.

The agent is hosted using the [Azure AI AgentServer SDK](https://pypi.org/project/azure-ai-agentserver-agentframework/) and can be deployed to Microsoft Foundry.

## How It Works

### Local Tools Integration

In [main.py](main.py), the agent uses a local Python function (`get_available_hotels`) that simulates a hotel availability API. This demonstrates how code-based agents can execute custom server-side logic that prompt agents cannot access.

The tool accepts:

- **check_in_date** - Check-in date in YYYY-MM-DD format
- **check_out_date** - Check-out date in YYYY-MM-DD format
- **max_price** - Maximum price per night in USD (optional, defaults to $500)

### Agent Hosting

The agent is hosted using the [Azure AI AgentServer SDK](https://pypi.org/project/azure-ai-agentserver-agentframework/),
which provisions a REST API endpoint compatible with the OpenAI Responses protocol.

## Quick Start

### UV Installation
- On Linux / macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- On Windows: `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

### Setup Steps
```bash
# 1. **MKDIR** the new folder and and **CD** into it

# 2 Create the environment
uv init . --python 3.13

# 3. Create the local virtual environment
uv venv

# 4. Activate the environment:
source .venv/bin/activate # on Linux/macOS
.\.venv\Scripts\activate.ps1 # on Windows

# 5. Add libraries (it's KEY to use `--active`):
uv add --active $(cat requirements.txt) --prerelease=allow # Automatically
uv add --active <package-name> --prerelease=allow # Manually

# 6. Check that the packges are installed
uv pip list

# 7. Synchronize to create the file structure (not needed in normal situations, just with pre-existing pyproject.toml
uv sync --active --prerelease=allow

# 8. List jupyter kernels
jupyter kernelspec list

# 9. Delete a jupyter kernel
jupyter kernelspec uninstall responses

# 10. Create kernel for the jupyter notebook
python -m ipykernel install --name responses --use

# 11. To deactivate
deactivate
```


## Running the Agent Locally: Local Container Build & Test
The .dockerignore intentionally excludes .env from the build context (so it never reaches Docker).
This is correct security behaviour: you should never bake secrets into an image.
So, don't use .env from the COPY instruction, but pass the .env at runtime instead:
```bash
# Build the image
docker build -t mcp-onedrive-demo .

# Run the container (mapping host port 8010 → container port 8000)
docker run -p 8010:8000 \
  -e AZURE_TENANT_ID=<your-tenant-id> \
  -e AZURE_CLIENT_ID=<your-client-id> \
  -e AZURE_CLIENT_SECRET=<your-client-secret> 
  <image-name>
  
# or, since they're already defined in your .env file, pass them without values to inherit from the current shell environment:
docker run -p 8010:8000 --env-file .env <image-name>

# such variables might be defined in our shell's startup file.
# For bash, append to ~/.bashrc (interactive shells) or ~/.bash_profile (login shells):
echo 'export AZURE_TENANT_ID=3ad***' >> ~/.bashrc
echo 'export AZURE_CLIENT_ID=31***' >> ~/.bashrc
echo 'export AZURE_CLIENT_SECRET=F5***' >> ~/.bashrc
source ~/.bashrc
```


## Additional Resources

- [Microsoft Agents Framework](https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview)
- [Managed Identities for Azure Resources](https://learn.microsoft.com/en-us/entra/identity/managed-identities-azure-resources/)
