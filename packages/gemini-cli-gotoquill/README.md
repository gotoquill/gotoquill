# Gotoquill for Gemini CLI

This terminal extension is separate from consumer Gemini Connected Apps. From the repository root, install a local copy:

```sh
gemini extensions install ./packages/gemini-cli-gotoquill
```

The manifest connects to the hosted service at `https://mcp.gotoquill.com/mcp`. For a different endpoint, edit `mcpServers.gotoquill.httpUrl` in your local copy before installing. Keep credentials out of commits. Hosted setup guides are at [Support](https://gotoquill.com/support/).

OAuth is discovered from server metadata. Use `/mcp auth gotoquill` when ready to authorize manually. Human signing consent is always required. This extension does not enable automatic tool trust.

[Extension reference](https://geminicli.com/docs/extensions/reference/) and [MCP OAuth discovery](https://geminicli.com/docs/tools/mcp-server/).
