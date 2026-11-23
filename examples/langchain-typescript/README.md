# Gotoquill with LangChain and LangGraph (TypeScript)

Runnable Node example using official `@langchain/mcp-adapters` 2.x. Use Node 22
or later. No LLM API key is needed. The default run only discovers tools.

## Install from your authorized checkout

From the repository root:

```bash
uv sync --extra dev
cd packages/langchain-gotoquill/js
npm ci
npm run build
cd ../../../examples/langchain-typescript
npm ci
npx tsc --noEmit
GOTOQUILL_COMMAND="$(pwd)/../../.venv/bin/gotoquill" npm start -- local
```

Windows uses `.venv/Scripts/gotoquill.exe`. The helper is a local `file:` dependency,
not an npm release. Both package lockfiles are committed. Run the Local MCP server with `uvx gotoquill mcp`. Source is available at
https://github.com/gotoquill/gotoquill.

## Choose Local or Cloud in one block

`connection()` in `main.ts` passes one option block to the shared helper:

```typescript
const local = { command: "gotoquill", args: ["mcp"] };
const cloud = {
  url: "https://mcp.gotoquill.com/mcp",
  headers: { Authorization: `Bearer ${oauthAccessToken}` },
};
const session = await connectGotoquill(local); // Select local OR cloud.
try {
  // Pass session.tools to your agent or invoke signingGraph here.
} finally {
  await session.close();
}
```

Provide `GOTOQUILL_ACCESS_TOKEN` privately via your OAuth integration, then run
`npm start -- cloud`. The token belongs to the Gotoquill user, not to a model
provider. Do not print, commit or trace it. The helper also accepts an SDK
`OAuthClientProvider` as `authProvider`; your app implements redirect, callback,
state validation and per-user storage as documented by LangChain. This example
uses an existing bearer token and does not create accounts or complete OAuth.

In 2.x a `url` selects Streamable HTTP, and explicit `transport: "http"` is
optional. It is not `streamable_http` in TypeScript. The earlier 1.x API was
`MultiServerMCPClient` / `getTools()` with `transport: "http"`; this example and
the updated draft helper use `MCPAdapter` / `listTools()` and explicit `close()`.

## Human consent, waiting, and switching

On a computer with a browser:

```bash
GOTOQUILL_COMMAND="$(pwd)/../../.venv/bin/gotoquill" npm start -- local \
  --request --pdf "$(pwd)/../sample_contract.pdf"
# With GOTOQUILL_ACCESS_TOKEN already supplied privately:
npm start -- cloud --request
```

Cloud uses the built-in sample NDA for Dana Cohen, Party A. Local uses the checkout
sample. The graph opens the returned `sign_url` in the browser, then checks status
every five seconds for up to ten minutes. LangChain provides no in-chat signing
card here. Human review and explicit signing UI consent are required. A model,
OAuth approval, or graph resume cannot provide that consent.

Replace `presentLink` with private link display in your authenticated app UI when
the agent runs on a server. Do not log signing links, credentials, PDFs or tool
results. Disable LangSmith tracing for these tools unless sensitive inputs and
outputs are redacted. Return the graph's `signed_pdf_path` or `signed_pdf_url`
privately only on `completed`. The CLI prints status only. Other terminal states
must not be described as signed.

A bounded wait leaves a request pending. Persist its ID and originating connection
for later checks. Keep Local running while a localhost signing page is needed.
Production apps should checkpoint before handoff and use durable wait/resume.
For a model-driven LangChain agent, pass `session.tools` to
`createAgent({model, tools: session.tools})` inside the same session lifetime.
Expose request/status tools, not internal signing UI tools, to that model.

To switch, change the configuration block or mode argument. Connect and verify
the destination's actual schemas before new requests. Finish pending work on its
original session, then retire that connection. This does not migrate documents,
keys, or pending requests. Cloud cannot read a local path, and tools, wait limits
and result formats differ. Errors never switch to Cloud automatically.

## Tests

The TypeScript tests use the Python mock MCP fixture, so prepare it once:

```bash
cd ../langchain-python
uv sync --group dev
cd ../langchain-typescript
npm test
npx tsc --noEmit
```

Tests run the real adapter and LangGraph over stdio, hand off a signing link,
check pending status and simulate a decline. They never submit a signature.
The Local discovery command above separately exercises the real Gotoquill server.

Official references verified on 19 November 2026:
[MCP guide](https://docs.langchain.com/oss/javascript/langchain/mcp),
[authentication and OAuth providers](https://docs.langchain.com/oss/javascript/langchain/mcp/auth),
[1.x API and transports](https://docs.langchain.com/oss/javascript/langchain/mcp-v1).
