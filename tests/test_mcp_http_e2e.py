"""End-to-end: MCP Python client over Streamable HTTP (and optional cloudflared tunnel)."""
from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import httpx2 as httpx
import pytest
import uvicorn

from gotoquill.mcp_http import create_http_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def http_mcp_server(tmp_path, monkeypatch):
    monkeypatch.setenv("GOTOQUILL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GOTOQUILL_CONFIG_DIR", str(tmp_path / "cfg"))
    port = _free_port()
    app, code, _ = create_http_app(public_base=f"http://127.0.0.1:{port}")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn failed to start"
    yield {"url": f"http://127.0.0.1:{port}/mcp", "base": f"http://127.0.0.1:{port}",
           "code": code, "port": port}
    server.should_exit = True
    t.join(timeout=5)


@pytest.mark.anyio
async def test_mcp_client_tools_list(http_mcp_server):
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {http_mcp_server['code']}"}
    async with httpx.AsyncClient(headers=headers, timeout=30.0) as http:
        async with streamable_http_client(http_mcp_server["url"], http_client=http) as streams:
            # TransportStreams may be a tuple or object
            read, write, *_ = streams
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                name = getattr(getattr(init, "server_info", None), "name", None) or str(init)
                assert "gotoquill" in name
                tools = await session.list_tools()
                names = {t.name for t in tools.tools}
                assert "request_signature" in names
                assert "wait_for_signature" in names
                assert "sign_pdf" in names


@pytest.mark.anyio
async def test_mcp_client_through_cloudflared(http_mcp_server):
    """Optional: if cloudflared can be installed, hit /mcp via a quick tunnel."""
    from gotoquill.tunnel import CloudflareTunnel, TunnelError, find_cloudflared

    try:
        find_cloudflared(auto_download=True)
    except TunnelError as e:
        pytest.skip(f"cloudflared unavailable: {e}")

    tunnel = CloudflareTunnel(http_mcp_server["port"], timeout=60)
    try:
        url = tunnel.start()
    except TunnelError as e:
        pytest.skip(f"quick tunnel failed (network?): {e}")

    # healthz through tunnel (may need DNS settle)
    ok = False
    for _ in range(20):
        try:
            r = httpx.get(f"{url}/healthz", timeout=10.0)
            if r.status_code == 200:
                ok = True
                break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    if not ok:
        tunnel.stop()
        pytest.skip("tunnel URL never answered /healthz")

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    headers = {"Authorization": f"Bearer {http_mcp_server['code']}"}
    async with httpx.AsyncClient(headers=headers, timeout=60.0) as http:
        async with streamable_http_client(f"{url}/mcp", http_client=http) as streams:
            read, write, *_ = streams
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init is not None
                tools = await session.list_tools()
                assert any(t.name == "request_signature" for t in tools.tools)
    tunnel.stop()
