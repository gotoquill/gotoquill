#!/usr/bin/env node
const cmd = process.argv[2];
if (cmd === "mcp") {
  await import("./mcp-stdio.js");
} else {
  console.log(`gotoquill (TypeScript draft)

Usage:
  gotoquill mcp     Start stdio MCP server

Env: GOTOQUILL_* (AGENT_SIGN_* fallback). Not published to npm yet.
`);
  process.exit(cmd ? 1 : 0);
}
