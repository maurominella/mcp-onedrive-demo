# Required env vars (MCP_CLIENT_ID, MCP_CLIENT_SECRET, MCP_TENANT_ID are mandatory;
# APPLICATIONINSIGHTS_CONNECTION_STRING is optional — omit to disable App Insights):
#
#   docker run -p 8010:8000 \
#     -e MCP_CLIENT_ID=<your-client-id> \
#     -e MCP_CLIENT_SECRET=<your-client-secret> \
#     -e MCP_TENANT_ID=<your-tenant-id> \
#     -e APPLICATIONINSIGHTS_CONNECTION_STRING=<your-connection-string> \
#     <image-name>
#
#   Or, using an env file (e.g., .env):
#   docker run -p 8010:8000 --env-file .env <image-name>

FROM python:3.13-slim

WORKDIR /app

# Copy requirements first to leverage Docker layer caching:
# pip install is re-executed only when requirements.txt changes,
# not on every source code change.
COPY requirements.txt ./

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy source code after dependencies — changes here only invalidate this layer.
COPY mcp_server.py auth.py ./

# EXPOSE is metadata only — it does not open or map any port.
# The actual host-to-container mapping is specified at runtime (e.g. -p 8010:8000).
EXPOSE 8000

CMD ["python", "mcp_server.py"]
