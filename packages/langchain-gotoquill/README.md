# langchain-gotoquill

Unpublished helpers for the official LangChain MCP adapters. Do not publish
these packages. Runnable examples and tests live in
[Python](../../examples/langchain-python/README.md) and
[TypeScript](../../examples/langchain-typescript/README.md).

Python uses `async with gotoquill_tools(command=..., args=...) as tools`, or
`url=...` with `auth`/`headers`. It wraps `langchain[mcp]`'s `MCPAdapter` and keeps
the connection alive through the context. Python 3.11 or later is required.

TypeScript uses `connectGotoquill({command, args})`, or `{url, headers}` /
`{url, authProvider}`. It returns `{tools, close}`; call `close()` in `finally`.
It wraps `@langchain/mcp-adapters` 2.x. Use `npm ci && npm run build` here before
installing the TypeScript example's local file dependency.

The earlier draft `load_gotoquill_tools` / `loadGotoquillTools` APIs were replaced
because they could not express connection lifetime consistently. There were no
repository callers. These helpers and the examples now share one API per language.
The Python standalone adapter is archived; current docs recommend
`langchain[mcp]`. TypeScript 1.x `MultiServerMCPClient` is superseded by
`MCPAdapter` in 2.x. See the cited official migration references in the examples.

Mode changes only affect new requests. Do not close a session with pending work
that still needs its process or switch automatically after an error. Both wrappers
reject mixed Local and Cloud options. Cloud requires OAuth; use per-user secrets.
These helpers do not render signing cards or consent on a person's behalf.
