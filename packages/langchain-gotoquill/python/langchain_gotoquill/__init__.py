"""Unpublished helpers using the official langchain.mcp adapter."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

CLOUD_URL = "https://mcp.gotoquill.com/mcp"


@asynccontextmanager
async def gotoquill_tools(
    *, command: str | None = None, args: list[str] | None = None,
    url: str | None = None, headers: dict[str, str] | None = None,
    auth: Any = None,
) -> AsyncIterator[list[Any]]:
    """Keep the connection alive through request, human review, and status checks.

    Local defaults to the preinstalled gotoquill executable. Cloud accepts
    auth="oauth" or an OAuth access token, or application-managed headers.
    Select exactly one mode; transport errors never switch modes.
    """
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport, StreamableHttpTransport
    from langchain.mcp import MCPAdapter

    if url is not None and (command is not None or args is not None):
        raise ValueError("Choose either Local command/args or Cloud URL")
    if url is None and (headers is not None or auth is not None):
        raise ValueError("Authentication is only valid for Cloud")
    transport = (
        StreamableHttpTransport(url, headers=headers)
        if url is not None
        else StdioTransport(command or "gotoquill", args if args is not None else ["mcp"])
    )
    async with MCPAdapter(Client(transport, auth=auth)) as adapter:
        yield await adapter.list_tools()


__all__ = ["CLOUD_URL", "gotoquill_tools"]
