###################################################################################################
# 1) APP-TOKEN (a.k.a. foundry_token)
#
# This is the *application token* that identifies the Foundry application itself.
# It does NOT represent the user and cannot be used as a user token.
#
# The MCP Server uses it to verify that the caller application is indeed Foundry.
# Since it is issued by Entra ID, Foundry does not require any special configuration
# to accept it (no need to register or trust the MCP app inside Foundry).
#
# The MCP Server uses this app-token ONLY as the "client assertion" in the OBO flow,
# to exchange the user-token (issued for Foundry) into a Graph token.
#
# The app-token is NEVER used to call Graph directly.
# It serves only to authenticate Foundry and to complete the OBO flow.
###################################################################################################


###################################################################################################
# 2) USER-TOKEN (the one Foundry sends to the MCP Server)
#
# This is the *user-delegated token* that Foundry obtains on behalf of the human user.
# It represents the end-user interacting with Copilot / Foundry.
#
# This token has audience: https://ai.azure.com
# (NOT https://graph.microsoft.com, NOT api://..., NOT the ARM resource ID).
#
# The MCP Server receives this token from Foundry and uses it as the "subject token"
# in the OBO flow. The MCP Server exchanges THIS token for a Graph token.
#
# This is the ONLY user-token that participates in the real Foundry → MCP → Graph flow.
# It is NOT the same as the CLI user token, and it is NOT created by the MCP Server.
#
# In short: this is the real end-user identity inside Foundry, and it is the token
# that must be exchanged for a Graph token via OBO.
###################################################################################################


###################################################################################################
# 3) USER-TOKEN (CLI) — obtained via AzureCliCredential()
#
# user_token = AzureCliCredential().get_token("https://graph.microsoft.com/.default").token
#
# This token represents the *developer* currently logged in with `az login`.
# It is issued for Microsoft Graph (audience: https://graph.microsoft.com).
#
# This token is useful ONLY for local testing, debugging, or calling Graph directly
# as the signed-in developer.
#
# It is NOT used in the Foundry → MCP → Graph OBO flow. (In realtà è un OBO "banale")
# It does NOT represent the Foundry user.
# It does NOT replace the user-token that Foundry sends to the MCP Server.
#
# In short: this CLI user-token represents the developer, not Foundry and not the
# end-user inside Copilot. It is only for local dev scenarios, not for production OBO.
###################################################################################################


"""
This sample demonstrates how to implement an MCP Server that performs OBO to Graph 
when called from a Foundry Agent. The flow is as follows:
✔️ Your Python client obtains a Graph token
✔️ It passes it to Foundry via x-ms-user-token
✔️ Foundry forwards it to your MCP Server
✔️ Your MCP Server performs OBO to Graph
✔️ Graph returns a "new" (but equivalent) Graph token
✔️ Your MCP Server uses that token to call /me/drive/root/children
👉 The OBO happens in your MCP Server, not on the consent page.

🧩 Perché servono due autenticazioni distinte?
1️⃣ DefaultAzureCredential → rappresenta l'IDENTITÀ dell'applicazione che chiama Foundry
Questo token serve a:
- autenticare la tua app verso Foundry
- dire "sono l'app X, registrata nel tenant Y"
- NON rappresenta l'utente
- NON contiene nome, email, UPN
- è un token app-only
- è quello che Foundry usa per capire chi è l'app che sta chiedendo di eseguire un tool


2️⃣ AzureCliCredential → rappresenta l'IDENTITÀ dell'utente che deve fare OBO
Questo token serve a:
- rappresentare Mauro come utente
- portare i suoi permessi verso Graph
- essere passato al tuo MCP Server
- essere scambiato con un token Graph via OBO
- contenere UPN, oid, tid, ecc.


🧠 Perché Foundry richiede il consenso solo per il token utente?
Perché il consenso riguarda l'utente, non l'app.

Foundry deve chiedere: "Mauro, autorizzi questa app a usare il tuo token per chiamare Graph?"


🧨 Perché è controintuitivo?
Perché nella tua testa (giustamente) pensi:
"Sto usando lo stesso account Entra ID, perché devo autenticarmi due volte?"

La risposta è:
✔️ Perché stai impersonando due ruoli diversi:
ruolo 1 → l'applicazione (DefaultAzureCredential)
ruolo 2 → l'utente (AzureCliCredential)

E questi due ruoli non possono mai essere fusi in un token unico.


🧩 Schema finale (quello che devi ricordare)
DefaultAzureCredential → app token
- usato per autenticare la tua app verso Foundry
- non contiene nome utente
- non richiede consenso utente
- non partecipa a OBO

AzureCliCredential → token utente
- usato per OBO verso Graph
- contiene UPN, oid, ecc.
- richiede consenso OAuth
- è quello che Foundry deve chiederti di autorizzare

🎉 Conclusione
Non è un bug, non è un comportamento strano, non è un problema di VS Code o CLI.

È proprio così che funziona OAuth 2.0 On-Behalf-Of:
- l'app si autentica come app,
- l'utente si autentica come utente,
- e OBO combina le due identità.
"""

from azure.identity import DefaultAzureCredential, AzureCliCredential
"""
- DefaultAzureCredential() è solo un motore
- AIProjectClient gli dice: "Ottienimi un token per questa audience Foundry"
- DefaultAzureCredential() risponde: "Ecco un token per questa audience, credi a me, sono un motore 
  che prova diverse strategie per ottenere un token, e questa è quella che ha funzionato"       

For DefaultAzureCredential, the credentials chain is:
- EnvironmentCredential
- ManagedIdentityCredential
- SharedTokenCacheCredential
- VisualStudioCodeCredential
- AzureCliCredential
- AzurePowerShellCredential
"""

# requires azure-ai-projects>=2.1.0, for example uv add --active azure-ai-projects --prerelease=allow
from azure.ai.projects import AIProjectClient
import requests

# 0. Variables
my_agent = "custom-mcp-agent-01"
my_version = "5"
project_endpoint = "https://foundry7159.services.ai.azure.com/api/projects/aif7159-standard-agent-project"


# 1. Retrieve the Graph token for the authenticated user
cli_cred = AzureCliCredential()
user_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6IndoMDZzRWt6TEhKNXNOTmFVeVJZMl82TzhLMCIsImtpZCI6IndoMDZzRWt6TEhKNXNOTmFVeVJZMl82TzhLMCJ9.eyJhdWQiOiJhcGk6Ly8yN2U3NGRkMy0yMTRkLTRmMDEtYTNiZC1kODZhNTEwZjJlZDciLCJpc3MiOiJodHRwczovL3N0cy53aW5kb3dzLm5ldC8zYWQwYjkwNS0zNGFiLTQxMTYtOTNkOS1jMWRjYzJkMzVhZjYvIiwiaWF0IjoxNzgxNzc5NDY5LCJuYmYiOjE3ODE3Nzk0NjksImV4cCI6MTc4MTc4NDk5NCwiYWNyIjoiMSIsImFpbyI6IkFaUUFhLzhjQUFBQTQ4elNTTGZxRkpydkVhcW5BRWtCODNVVWRCV1d0TytBVWFHTjBIUi9aNkpCbmJuTExRZzJLN2ZkU2FnM05EZlk4cHY2OCttalViYTNjRDc1d0tQQVhhaFhYbWZYUytmbGJzRkNSTFBqMzFmZmdVTFp1YW5QODg3d2FuL0tNNTF5Ym5Dd2NzaHd1QXpkRWU4NEQxNFNBcGs0bFZ6K2prNitqYTU2UmcrMVNrT29MSENvRG13dzZkN3lsV3VFMkNMdSIsImFtciI6WyJwd2QiLCJyc2EiLCJtZmEiXSwiYXBwaWQiOiIwNGIwNzc5NS04ZGRiLTQ2MWEtYmJlZS0wMmY5ZTFiZjdiNDYiLCJhcHBpZGFjciI6IjAiLCJkZXZpY2VpZCI6ImM2ZDc4MzRjLWM1M2EtNGQ1NS04Y2JmLTAzYjBjN2VlN2IyZiIsImZhbWlseV9uYW1lIjoiTWluZWxsYSIsImdpdmVuX25hbWUiOiJNYXVybyIsImlwYWRkciI6IjQwLjY4LjIwMC42MyIsIm5hbWUiOiJNYXVybyBNaW5lbGxhIiwib2lkIjoiNjhjNGJmMWUtN2M0OS00ZjkyLWE4ZjUtMGQzMzE4MzFjNTFhIiwicHdkX3VybCI6Imh0dHBzOi8vZ28ubWljcm9zb2Z0LmNvbS9md2xpbmsvP2xpbmtpZD0yMjI0MTk4IiwicmgiOiIxLkFiMEFCYm5RT3FzMEZrR1QyY0hjd3ROYTl0Tk41eWROSVFGUG83M1lhbEVQTHRjQUFFSzlBQS4iLCJzY3AiOiJhY2Nlc3NfYXNfdXNlciIsInNpZCI6IjAwMmU0M2RhLTIxNmYtOTk4Ny0zNTJiLTA3ZTczYzA3MDgyMiIsInN1YiI6Ik93ci1ZVUpianZGNnd0eVFQRnlJU09OYUMwRldFcmQxcFN5ZE5odzhTRzAiLCJ0aWQiOiIzYWQwYjkwNS0zNGFiLTQxMTYtOTNkOS1jMWRjYzJkMzVhZjYiLCJ1bmlxdWVfbmFtZSI6Im1hdXJvLm1pbmVsbGFATW5nRW52TUNBUDg4MzY1Mi5vbm1pY3Jvc29mdC5jb20iLCJ1cG4iOiJtYXVyby5taW5lbGxhQE1uZ0Vudk1DQVA4ODM2NTIub25taWNyb3NvZnQuY29tIiwidXRpIjoiQ3lMaThOcl9Pa0N1bk9MSjBqeGFBQSIsInZlciI6IjEuMCIsInhtc19mdGQiOiJEdEg5NGtXWWhBX1RCbFpfS2RzLW55cE9uN1lSYkt2d1JDQ1B1SEl4NS1vQmRYTmxZWE4wTFdSemJYTSJ9.EIPVMHAUXeDkio8LFI4K1M9w5JyO_xmbedAoCwQgen9ACAcb8kE0B3HKrSFDvS4WFFeptvweV7dJMKe0RJA8nHqT2T0ryQvG3rclqbSREHcQjxO8rAjAU5enZX9UJbFi8INQ7xOfNkGCjevZKPFmBX52MBtvQuMudQjy6hWZSrcCm-i6JdPpNtpoyBK7uTbnwpohkrlBFdexEdRrLI6Y0UeusXIb2KJG-Hi6UjwYESYwOQSNq2m-n3eiE4CYTcYNLwVRWVlQil8SknA9pL5NuWnqgGAYdy1QESU5YJdoRYL-hdOpv3g2zFQaz6f79XZKKPFVZGZfkTa9pbUh-jbRaA" # cli_cred.get_token("https://graph.microsoft.com/.default").token


# 2. Setup Foundry client
# exclude VSCode credential to avoid
# issues with token caching, but you can choose to include it if you use VSCode and are signed in there
default_cred = DefaultAzureCredential(
    exclude_visual_studio_code_credential=True
) 

# foundry_token is the app-token that identifies the Foundry application. 
# It does NOT represent the user and cannot be used as a user token.
# The MCP Server uses it to verify that the caller is indeed Foundry.
# Since it is issued by Entra ID, Foundry does not need any special configuration 
# to accept it (no need to register or trust the MCP app inside Foundry).
# The MCP Server uses this app-token only as the "client assertion" in the OBO flow,
# to exchange the user-token (issued for Foundry) into a Graph token.
# The app-token is never used to call Graph directly.
# L'app‑token serve solo al MCP server per autenticare Foundry e per completare l’OBO.
# Non rappresenta l'utente, non chiama Graph, non chiama Foundry.
foundry_token = default_cred.get_token("https://ai.azure.com/.default").token

project_client = AIProjectClient(
    endpoint=project_endpoint,
    credential=default_cred,
)
openai_client = project_client.get_openai_client()

# 3. Query to activate the MCP tool
# "how much is 2+2?"
# "Tell me what you can help with."
# "create a chart with the top-level folders of my OneDrive account, together with their size"
query = "create a chart with the top-level folders of my OneDrive account, together with their size"


# 4. Invoke the agent, passing the token in the Authorization header and the agent reference in the body
response = openai_client.responses.create(
    input=[{"role": "user", "content": query}],
    extra_headers={"x-ms-user-token": user_token},
    extra_body={"agent_reference": {"name": my_agent, "version": my_version, "type": "agent_reference"}},
)


# 5. Check if consent is required for the OBO exchange, and if so, print the URL to consent and wait for the user to consent 
# before calling the agent again. Note that the OBO exchange happens in your MCP Server, not on the consent page.
tool_call = response.output[1]
if tool_call.type == "oauth_consent_request":
    url = tool_call.model_extra["consent_link"]
    print("Open this URL to consent:", url)
    # wait for user to consent and then call the agent again
    if input("Have you authorized (Y/N)? > ").lower() == "n":
        print("Sorry, you need to consent to use this tool. Now exiting.")
        exit(0)

    response = openai_client.responses.create(
        input=[{"role": "user", "content": query}],
        extra_headers={"x-ms-user-token": user_token},
        extra_body={"agent_reference": {"name": my_agent, "version": my_version, "type": "agent_reference"}},
    )



# 6. Final response
print(f"Response output: {response.output_text}")