import asyncio
import sys
from pathlib import Path

import pytest
from langchain_gotoquill import gotoquill_tools
from main import connection, signing_graph


def test_modes_and_missing_credentials(monkeypatch):
    monkeypatch.delenv("GOTOQUILL_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("GOTOQUILL_COMMAND", "/authorized/venv/bin/gotoquill")
    assert connection("local") == {"command": "/authorized/venv/bin/gotoquill", "args": ["mcp"]}
    with pytest.raises(ValueError, match="OAuth access token"):
        connection("cloud")
    with pytest.raises(ValueError, match="Choose"):
        connection("typo")


def test_real_adapter_and_graph_preserve_origin_and_wait_for_human():
    async def run():
        links = []
        async def present_link(url):
            links.append(url)
        async with gotoquill_tools(command=sys.executable, args=[str(Path(__file__).with_name("mock_server.py"))]) as tools:
            result = await signing_graph(tools, {"signer_name": "Dana Cohen"}, present_link, poll_seconds=0).ainvoke({})
        assert links == ["https://signing.invalid/review"]
        assert result["request_id"] == "fixture-dana"
        assert result["status"] == "declined"
    asyncio.run(run())


def test_timeout_keeps_pending_request():
    async def run():
        async def present_link(url):
            pass
        async with gotoquill_tools(command=sys.executable, args=[str(Path(__file__).with_name("mock_server.py"))]) as tools:
            result = await signing_graph(tools, {}, present_link, poll_seconds=0, max_checks=1).ainvoke({})
        assert result["status"] == "pending"
        assert result["request_id"] == "fixture-dana"
    asyncio.run(run())


def test_reject_mixed_modes():
    async def run():
        with pytest.raises(ValueError, match="either"):
            async with gotoquill_tools(url="https://mcp.gotoquill.com/mcp", command="gotoquill"):
                pass
    asyncio.run(run())
