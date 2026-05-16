FROM mcr.microsoft.com/devcontainers/python:3.12

WORKDIR /app

RUN pip install --no-cache-dir \
    "mcp[cli]" msal requests uvicorn \
    azure-identity azure-core

COPY mcp_server.py auth.py ./

EXPOSE 8000

CMD ["python", "mcp_server.py"]
