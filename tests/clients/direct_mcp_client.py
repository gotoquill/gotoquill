"""Model-free control client for scripts/client_matrix.py: plain MCP stdio client, same calls an agent should make.

    python tests/clients/direct_mcp_client.py <pdf> -- <server command...>
"""
from __future__ import annotations

import asyncio
import json
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(pdf: str, cmd: list[str]) -> None:
    env = {k: v for k, v in os.environ.items()}
    params = StdioServerParameters(command=cmd[0], args=cmd[1:], env=env)
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = [t.name for t in (await s.list_tools()).tools]
        print("tools:", ", ".join(tools), flush=True)
        res = await s.call_tool("request_signature", {"pdf_path": pdf, "signer_name": "Test Signer", "delivery": "page"})
        req = json.loads(res.content[0].text)
        print("request_signature ->", req.get("request_id"), req.get("status"), flush=True)
        res = await s.call_tool("wait_for_signature", {"request_id": req["request_id"], "wait_seconds": 300})
        st = json.loads(res.content[0].text)
        print("wait_for_signature ->", st.get("status"), flush=True)
        print("signed_pdf_path:", st.get("signed_pdf_path"), flush=True)


if __name__ == "__main__":
    i = sys.argv.index("--")
    asyncio.run(main(sys.argv[1], sys.argv[i + 1:]))
