"""MCP surface hardening for small/weak models: lenient inputs, defaults, next-step hints, sign_pdf."""
import os
import threading
import time
from pathlib import Path

import anyio
import httpx

from gotoquill import lenient as L
from test_flow import _mcp_call, sign_body


def test_norm_path_variants(tmp_path, monkeypatch):
    f = tmp_path / "my doc.pdf"
    f.write_bytes(b"%PDF-1.4")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    want = str(f.resolve())
    assert L.norm_path("my doc.pdf") == want
    assert L.norm_path("./my doc") == want
    assert L.norm_path("~/my doc.pdf") == want
    assert L.norm_path("file://" + str(f).replace(" ", "%20")) == want
    assert L.norm_path(f'"{f}"') == want
    assert L.norm_path("  ") is None
    assert L.norm_path("out", must_exist=False).endswith("out.pdf")


def test_coercions_and_ids():
    assert L.as_float("600") == 600 and L.as_float("10s") == 10 and L.as_float("x", 5) == 5
    assert L.as_int("30") == 30 and L.as_int("30.0") == 30 and L.as_int(None) is None
    assert L.as_bool("true") is True and L.as_bool("no") is False and L.as_bool(None, None) is None
    assert L.as_json('[{"page": 1}]') == [{"page": 1}] and L.as_json("all") == "all"
    assert L.norm_delivery("Local") == "page" and L.norm_delivery(None) == "link"
    assert L.extract_request_id("request_id=req_0123456789abcdef") == "req_0123456789abcdef"
    for p in ("", "<request_id>", "$(result)", "{request_id}", "sample-request-uuid", "REQUEST_ID"):
        assert L.is_placeholder(p), p
    assert not L.is_placeholder("req_0123456789abcdef")


def _signer_thread(env):
    def run():
        for _ in range(400):
            for s in list(env.sessions.values()):
                if s.sign_url:
                    httpx.post(s.sign_url + "/submit", json=sign_body())
                    return
            time.sleep(0.05)
    threading.Thread(target=run, daemon=True).start()


def test_lenient_request_and_placeholder_wait(env, pdf_file, monkeypatch):
    from gotoquill.mcp_server import build_server
    srv = build_server()
    call = _mcp_call(srv)
    monkeypatch.chdir(pdf_file.parent)

    async def flow():
        tools = {t.name: t for t in await srv.list_tools()}
        rs = tools["request_signature"]
        req_schema = (getattr(rs, "input_schema", None) or getattr(rs, "inputSchema", None) or rs.parameters)
        # pdf_path is preferred locally; pdf_base64 / pdf_url are alternatives for remote MCP
        props = req_schema.get("properties") or {}
        assert "pdf_path" in props
        assert "pdf_base64" in props and "pdf_url" in props
        required = req_schema.get("required") or []
        assert "pdf_path" in required or required == []  # optional when cloud inputs exist
        for name in ("request_signature", "sign_pdf", "wait_for_signature", "get_signature_status"):
            assert "Example:" in tools[name].description and len(tools[name].description) < 600, name
        # no-id wait before any request: clear hint
        e = await call("wait_for_signature", {"wait_seconds": 0})
        assert e["error"] and "request_signature" in e["next"]
        # missing file: error + hint
        m = await call("request_signature", {"pdf_path": "nope.pdf"})
        assert m["code"] == 404 and "next" in m
        # relative path without extension, string ints/bools, delivery synonym
        r = await call("request_signature", {"pdf_path": "contract", "delivery": "local", "open_browser": "false",
                                             "expires_in_minutes": "30", "add_date": "true", "signer_name": "Alex Example"})
        assert r["request_id"].startswith("req_"), r
        assert r["next_call"] == {"tool": "wait_for_signature", "arguments": {"request_id": r["request_id"]}}
        assert httpx.post(r["sign_url"] + "/submit", json=sign_body()).status_code == 200
        st = await call("wait_for_signature", {"request_id": "$(result)", "wait_seconds": "10"})
        assert st["status"] == "completed" and r["request_id"] in st["note"]
        assert Path(st["signed_pdf_path"]).exists()
        st2 = await call("get_signature_status", {})
        assert st2["status"] == "completed"
        # junk around a real id
        st3 = await call("get_signature_status", {"request_id": f"request_id={r['request_id']}"})
        assert st3["status"] == "completed" and "note" not in st3

    anyio.run(flow)


def test_pending_has_next_call(env, pdf_file):
    from gotoquill.mcp_server import build_server
    srv = build_server()
    call = _mcp_call(srv)

    async def flow():
        r = await call("request_signature", {"pdf_path": str(pdf_file), "delivery": "page", "open_browser": False})
        st = await call("wait_for_signature", {"request_id": r["request_id"], "wait_seconds": 0})
        assert st["status"] == "pending" and st["next_call"]["arguments"]["request_id"] == r["request_id"]
        assert "wait_for_signature" in st["next"]
        c = await call("cancel_request", {"request_id": "<request_id>"})
        assert "error" not in c, c

    anyio.run(flow)


def test_sign_pdf_one_call(env, pdf_file):
    from gotoquill.mcp_server import build_server
    srv = build_server()
    call = _mcp_call(srv)
    _signer_thread(env)

    async def flow():
        out = await call("sign_pdf", {"pdf_path": "file://" + str(pdf_file), "wait_seconds": "20",
                                      "signer_name": "Alex Example"})
        assert out["status"] == "completed", out
        assert Path(out["signed_pdf_path"]).exists() and out["signed_pdf_path"] in out["next"]

    anyio.run(flow)


def test_sign_pdf_link_returns_link_without_blocking(env, pdf_file):
    from gotoquill.mcp_server import build_server
    srv = build_server()
    call = _mcp_call(srv)

    async def flow():
        out = await call("sign_pdf", {"pdf_path": str(pdf_file), "delivery": "link"})
        assert out["sign_url"] in out["next"] and out["request_id"] in out["next"]

    anyio.run(flow)


def test_help_resource(env):
    from gotoquill.mcp_server import build_server
    srv = build_server()

    async def flow():
        c = list(await srv.read_resource("gotoquill://help"))[0]
        txt = c.content if hasattr(c, "content") else c.text
        assert "placements" in txt and "delivery" in txt

    anyio.run(flow)


def test_page_auto_waits_when_browser_opened(env, pdf_file, monkeypatch):
    import webbrowser

    from gotoquill.mcp_server import build_server
    monkeypatch.setattr(webbrowser, "open", lambda *a, **k: True)
    monkeypatch.setenv("GOTOQUILL_PAGE_AUTOWAIT", "20")
    srv = build_server()
    call = _mcp_call(srv)
    _signer_thread(env)

    async def flow():
        r = await call("request_signature", {"pdf_path": str(pdf_file), "delivery": "page", "open_browser": True})
        assert r["auto_waited"] and r["status"] == "completed", r
        assert Path(r["signed_pdf_path"]).exists() and "next_call" not in r
        # explicit wait_seconds=0 keeps the old return-immediately behaviour
        r2 = await call("request_signature", {"pdf_path": str(pdf_file), "delivery": "page", "open_browser": True,
                                              "wait_seconds": 0, "output_path": str(pdf_file.with_name("b.pdf"))})
        assert r2["status"] == "pending" and "auto_waited" not in r2

    anyio.run(flow)


def test_sign_pdf_path_alias_and_missing(env, pdf_file):
    from gotoquill.mcp_server import build_server
    srv = build_server()
    call = _mcp_call(srv)
    _signer_thread(env)

    async def flow():
        e = await call("sign_pdf", {})
        assert e["error"] and "sign_pdf(pdf_path=" in e["next"]
        out = await call("sign_pdf", {"path": str(pdf_file), "wait_seconds": 20})
        assert out["status"] == "completed", out

    anyio.run(flow)
