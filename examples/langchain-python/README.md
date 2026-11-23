# Gotoquill with LangChain and LangGraph (Python)

Runnable example using the official `langchain[mcp]` adapter. Python 3.11 or later
is required for this example (Gotoquill itself supports Python 3.10).
The graph needs no LLM API key. It discovers tools by default and creates a
pending request only with `--request`.

## Install from a source checkout

Run the MCP server with `uvx gotoquill mcp`. For this example and its local helper,
clone [gotoquill/gotoquill](https://github.com/gotoquill/gotoquill).

From the repository root:

```bash
uv sync --extra dev
cd examples/langchain-python
uv sync --group dev
# Use the absolute path to the root environment's installed executable:
GOTOQUILL_COMMAND="$(pwd)/../../.venv/bin/gotoquill" uv run python main.py
uv run pytest -q
```

On Windows, use the environment's `Scripts/gotoquill.exe` path. The local helper
is installed from `packages/langchain-gotoquill/python`, not PyPI. Dependencies
are locked in `uv.lock`.

## One configuration block selects the mode

`connection()` in `main.py` chooses one of these helper inputs:

```python
local = {"command": "gotoquill", "args": ["mcp"]}
cloud = {"url": "https://mcp.gotoquill.com/mcp", "auth": oauth_access_token}
# Use one, never both. oauth_access_token comes from your authorized OAuth flow.
async with gotoquill_tools(**local) as tools:
    # Pass tools to your LangChain agent or keep this context around a LangGraph run.
    ...
```

Cloud uses Streamable HTTP. Supply `GOTOQUILL_ACCESS_TOKEN` through your secret
manager or private environment, then run `uv run python main.py --mode cloud`.
It must be an OAuth access token for Gotoquill and this user, not a provider API
key or a fabricated token. The example never prints it. Expired tokens require
refresh or a new OAuth login; errors never trigger a fallback to another mode.

For interactive OAuth, the same helper accepts `auth="oauth"`, delegated to
FastMCP's OAuth client. In a deployed multi-user app, implement per-user credential
storage, browser redirect and callback handling using the official auth docs.
Do not share one user's Cloud credentials with other users.

## Human signing flow

To try Local on a computer with a browser, from this directory:

```bash
GOTOQUILL_COMMAND="$(pwd)/../../.venv/bin/gotoquill" uv run python main.py \
  --request --pdf "$(pwd)/../sample_contract.pdf"
```

For Cloud, after supplying the OAuth environment variable privately:

```bash
uv run python main.py --mode cloud --request
```

Cloud uses the built-in sample NDA for Dana Cohen, Party A. Local uses the sample
PDF from the checkout. The script opens `sign_url` in the browser and checks
status every five seconds, for up to ten minutes. No in-chat signing card is
provided by LangChain. The person must review and explicitly consent in the
signing UI. OAuth authorization and a graph resume are not signature consent.

The `present_link` callback is the integration point for your authenticated app
UI. In a hosted agent runtime, replace browser opening with that UI's private
link display. Links grant bearer access: do not write them to logs, tracing,
analytics, public files or shared transcripts. Disable LangSmith tracing for
these tools unless your application redacts their inputs and outputs.

The graph returns the final result. Deliver `signed_pdf_path` (Local) or
`signed_pdf_url` (Cloud) privately when status is `completed`; do not claim a
signature for `pending`, `declined`, `cancelled`, or `expired`. The CLI only
prints status. On timeout, preserve the returned request ID with the originating
connection and check it later. Keep the Local process alive if you selected
`delivery="page"` and the signer still needs its localhost page. Production
apps should checkpoint request IDs and connection identity before handoff and
use a durable wait/resume loop instead of tying a long wait to an HTTP request.

## Switch and verify

Change only the connection block (or `--mode`). Connect the destination, inspect
its actual tool schemas, and verify discovery before new work. Keep pending work
on its original connection; finish it before closing that session. Do not migrate
PDFs, keys or requests, and do not pass local filesystem paths to Cloud. Do not
assume identical tools, wait limits or result formats.

`signing_graph()` is a runnable deterministic LangGraph. For a model-driven agent,
pass the same tool list to LangChain's `create_agent(model, tools)` inside the
helper context. The model's workflow must present the human link and wait for a
terminal status; it must never call internal signing UI tools to synthesize
consent. The graph example calls only request and status tools.

## APIs verified on 19 November 2026

The original draft used `langchain-mcp-adapters` / `MultiServerMCPClient`.
That Python repository is now archived. Its transport names were `stdio` and
`streamable_http` (also `http`). The current official replacement is
`langchain[mcp]>=1.4`, `langchain.mcp.MCPAdapter`, and `list_tools()`. Transport
selection uses the executable or URL; authentication belongs on FastMCP's client.
The namespace is beta, so the example locks the tested versions. The helper was
updated with it, rather than adding a competing wrapper API.

Sources: [Python MCP guide](https://docs.langchain.com/oss/python/langchain/mcp),
[migration and transport mapping](https://docs.langchain.com/oss/python/migrate/langchain-mcp-adapters),
[authentication](https://docs.langchain.com/oss/python/langchain/mcp/auth),
[archived adapter](https://github.com/langchain-ai/langchain-mcp-adapters).

Tests use the real adapter against `mock_server.py` over stdio. It stays pending
once, then declines, so no signature is forged. A separate discovery smoke runs
against the real Local server without creating a request or contacting Cloud.
