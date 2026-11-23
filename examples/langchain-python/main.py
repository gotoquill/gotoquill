"""Discover Gotoquill tools and optionally request a human signature. No LLM key needed."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from typing import Any

from langchain_gotoquill import CLOUD_URL, gotoquill_tools
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict


def connection(mode: str) -> dict[str, Any]:
    # Switching changes this one block. Finish pending work before changing it.
    if mode == "local":
        return {"command": os.environ.get("GOTOQUILL_COMMAND", "gotoquill"), "args": ["mcp"]}
    if mode == "cloud":
        token = os.environ.get("GOTOQUILL_ACCESS_TOKEN")
        if not token:
            raise ValueError("Cloud needs an OAuth access token in GOTOQUILL_ACCESS_TOKEN")
        return {"url": CLOUD_URL, "auth": token}
    raise ValueError("Choose local or cloud")


def find_tool(tools: list[Any], name: str) -> Any:
    matches = [tool for tool in tools if tool.name == name or tool.name == "gotoquill_" + name]
    if len(matches) != 1:
        raise ValueError(f"Expected one {name} tool; refresh server schemas")
    return matches[0]


def payload(message: Any) -> dict[str, Any]:
    if getattr(message, "status", None) == "error":
        raise RuntimeError("MCP tool failed; inspect the request in your application")
    artifact = getattr(message, "artifact", None)
    if isinstance(artifact, dict):
        structured = artifact.get("structured_content") or artifact.get("structuredContent")
        if isinstance(structured, dict):
            return structured
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return json.loads(content)
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            try:
                value = json.loads(block["text"])
                if isinstance(value, dict):
                    return value
            except (ValueError, KeyError):
                continue
    raise ValueError("Expected structured Gotoquill tool output")


async def call(tool: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    # Tool-call form preserves the MCP artifact alongside the model-facing text.
    message = await tool.ainvoke({"name": tool.name, "args": arguments, "id": "gotoquill-example", "type": "tool_call"})
    return payload(message)


class SigningState(TypedDict, total=False):
    request_id: str
    status: str
    result: dict[str, Any]


def signing_graph(tools: list[Any], arguments: dict[str, Any], present_link, *, poll_seconds: float = 5, max_checks: int = 120):
    """A deterministic LangGraph flow; no model can supply a signature or consent."""
    async def request(state):
        result = await call(find_tool(tools, "request_signature"), arguments)
        if not result.get("sign_url") or not result.get("request_id"):
            raise RuntimeError("Request did not return a signing link")
        # Present only in the authenticated user's UI. Never send to analytics/logs.
        await present_link(result["sign_url"])
        return {"request_id": result["request_id"], "status": "pending"}

    async def wait(state):
        for _ in range(max_checks):
            result = await call(find_tool(tools, "get_signature_status"), {"request_id": state["request_id"]})
            if result.get("status") != "pending":
                return {"status": result.get("status", "unknown"), "result": result}
            await asyncio.sleep(poll_seconds)
        # A timeout never creates another request or switches connection.
        return {"status": "pending", "result": {"request_id": state["request_id"], "status": "pending"}}

    graph = StateGraph(SigningState)
    graph.add_node("request", request)
    graph.add_node("wait", wait)
    graph.add_edge(START, "request")
    graph.add_edge("request", "wait")
    graph.add_edge("wait", END)
    return graph.compile()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["local", "cloud"], default="local")
    parser.add_argument("--request", action="store_true", help="Create a pending sample request and open its human signing page")
    parser.add_argument("--pdf", help="Absolute local sample PDF path (Local only)")
    args = parser.parse_args()
    if args.mode == "cloud" and args.pdf:
        parser.error("Cloud sample mode does not accept a local path")
    if args.request and args.mode == "local" and not args.pdf:
        parser.error("Local requests need --pdf pointing to examples/sample_contract.pdf")
    async with gotoquill_tools(**connection(args.mode)) as tools:
        if not args.request:
            print("Connected tools:", ", ".join(tool.name for tool in tools))
            return
        arguments = {"sample": "nda", "signer_role": "Party A", "signer_name": "Dana Cohen"} if args.mode == "cloud" else {"pdf_path": args.pdf, "delivery": "page", "open_browser": False, "signer_name": "Dana Cohen"}

        async def present_link(url):
            import webbrowser
            if not webbrowser.open(url):
                raise RuntimeError("No browser available; provide a private signing-link UI callback")
            print("Opened the signing page. Review and consent there; waiting for completion.")

        result = await signing_graph(tools, arguments, present_link).ainvoke({})
        print("Request status:", result["status"])
        print("Return the result's signed_pdf_path or signed_pdf_url through your private application UI.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        # SDK errors may contain credential-bearing URLs or server-provided text.
        raise SystemExit("Gotoquill connection or request failed. Check mode, executable, OAuth and tool schemas privately.") from None
