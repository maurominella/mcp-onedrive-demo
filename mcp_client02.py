import os
from dotenv import load_dotenv
load_dotenv()  # MUST be first: env vars must be set before any import reads them

import msal
import requests


# === CONFIGURATION ===
CLIENT_ID = os.environ["MCP_CLIENT_ID"]
TENANT_ID = os.environ["MCP_TENANT_ID"]
scopes = ["api://AzureAIFoundry.User.Read/.default", "User.Read"]

authority = f"https://login.microsoftonline.com/{TENANT_ID}"


# === 1. CREATE MSAL APPLICATION ===
app = msal.PublicClientApplication(
    client_id=CLIENT_ID,
    authority=authority
)


# === 2. RETRIEVE USER'S TOKEN ===
result = app.acquire_token_interactive(scopes=scopes)

if "access_token" not in result:
    raise Exception("Error during user authentication")

user_token = result["access_token"]
print(f"User's token: {user_token[:60]}...")



# === 3. CALL RESPONSES API WITH USER TOKEN ===
endpoint = "https://<foundry-endpoint>/openai/responses?api-version=2024-10-01-preview"

payload = {
    "input": [
        {"role": "user", "content": "Tell me what permissions I have as a user."}
    ],
    "agent_reference": {
        "type": "agent_reference",
        "name": "promptagent-01",
        "version": "5"
    }
}

headers = {
    "Authorization": f"Bearer {user_token}",
    "Content-Type": "application/json"
}

response = requests.post(endpoint, json=payload, headers=headers)
print(response.json())