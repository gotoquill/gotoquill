import base64
import hashlib
import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
from pdfmake import Opened, sig_png  # noqa: F401 - sig_png is imported by other tests

ROOT = Path(__file__).resolve().parents[1]


def sign_body(**kw):
    return {"decision": "sign", "signature_png_base64": base64.b64encode(sig_png()).decode(),
            "method": "drawn", "signer_name": "Alex Example", "consent": True, **kw}


def port_open(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_closed(port: int, t: float = 5) -> bool:
    end = time.monotonic() + t
    while time.monotonic() < end:
        if not port_open(port):
            return True
        time.sleep(0.05)
    return False


def test_local_flow_binds_localhost_writes_files_and_shuts_down(env, pdf_file, sample_pdf):
    r = env.request(pdf_path=str(pdf_file), signer_name="Alex Example", add_date=True,
                    placements=[{"page": 1, "x": 72, "y": 580, "width": 200, "height": 58},
                                {"kind": "date", "page": 1, "x": 340, "y": 620, "width": 150, "height": 18}])
    url = r["sign_url"]
    assert url.startswith("http://127.0.0.1:") and r["browser_opened"] is False
    srv = env.sessions[r["request_id"]].server
    assert srv.sock.getsockname()[0] == "127.0.0.1" and srv.port not in (0, 8787)
    assert Path(r["output_path"]) == pdf_file.with_name("contract - signed.pdf")
    assert Path(r["audit_path"]) == pdf_file.with_name("contract - signed.audit.json")

    page = httpx.get(url)
    assert page.status_code == 200 and "signature" in page.text.lower() and "__GOTOQUILL_MODE__" not in page.text
    info = httpx.get(url + "/info").json()
    assert info["page_count"] == 1 and info["signer_name"] == "Alex Example" and "_id" not in info
    assert httpx.get(url + "/page/1.png").content.startswith(b"\x89PNG")
    assert env.status(r["request_id"])["status"] == "pending"

    assert httpx.post(url + "/submit", json=sign_body(), headers={"User-Agent": "pytest-browser/1.0"}).json()["status"] == "signed"
    st = env.status(r["request_id"], wait_seconds=10)
    assert st["status"] == "completed" and st["signer_name"] == "Alex Example"
    out = pdf_file.with_name("contract - signed.pdf").read_bytes()
    a = json.loads(pdf_file.with_name("contract - signed.audit.json").read_text())
    assert a["original_sha256"] == hashlib.sha256(sample_pdf).hexdigest()
    assert a["signed_sha256"] == hashlib.sha256(out).hexdigest()
    assert a["ip"] == "127.0.0.1" and a["user_agent"] == "pytest-browser/1.0" and a["consent_given"]
    assert a["signed_at"].endswith("Z") and a["method"] == "drawn"
    with Opened(out) as d:
        p = d[0]
        assert len(p.get_images()) == 1
        from datetime import datetime as _dt
        day = _dt.fromisoformat(a["signed_at"].replace("Z", "+00:00")).strftime("%d/%m/%Y")
        assert f"Signed {day}" in p.get_text() and "(UTC)" in p.get_text()
        assert p.min_pixel((72, 580, 272, 638)) < 100
    # temp page is gone
    assert wait_closed(srv.port) and env.status(r["request_id"])["page_running"] is False


def test_autodetect_field_typed_and_output_path(env, pdf_file, tmp_path):
    out = tmp_path / "out" / "final.pdf"
    out.parent.mkdir()
    r = env.request(pdf_path=str(pdf_file), output_path=str(out))
    assert r["placements"][0]["field_name"] == "ContractorSignature"
    httpx.post(r["sign_url"] + "/submit", json=sign_body(method="typed", typed_name="Alex Example"))
    st = env.status(r["request_id"], wait_seconds=10)
    assert st["output_path"] == str(out) and Path(st["audit_path"]) == tmp_path / "out" / "final.audit.json"
    with Opened(out) as d:
        assert len(d[0].get_images()) == 1 and not list(d[0].widgets())
    assert st["audit"]["method"] == "typed"


def test_single_use_link(env, pdf_file):
    r = env.request(pdf_path=str(pdf_file), serve=False)
    from fastapi.testclient import TestClient
    from gotoquill.api import create_app
    c = TestClient(create_app())
    tok = env.sessions[r["request_id"]].sign_token
    assert c.post(f"/s/{tok}/submit", json=sign_body()).status_code == 200
    assert c.post(f"/s/{tok}/submit", json=sign_body()).status_code == 410
    assert c.get(f"/s/{tok}/page/1.png").status_code == 410
    assert c.get(f"/s/{tok}/info").json()["status"] == "signed"


def test_expiry_closes_page(env, pdf_file):
    from gotoquill import core
    r = env.request(pdf_path=str(pdf_file), expires_in_minutes=1)
    with core.get_service()._db() as c:
        c.execute("UPDATE requests SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (r["request_id"],))
    assert httpx.post(r["sign_url"] + "/submit", json=sign_body()).status_code == 410
    assert env.status(r["request_id"])["status"] == "expired"
    assert wait_closed(env.sessions[r["request_id"]].server.port)


def test_decline_and_cancel_shut_down(env, pdf_file):
    r = env.request(pdf_path=str(pdf_file))
    httpx.post(r["sign_url"] + "/submit", json={"decision": "decline", "decline_reason": "wrong rate"})
    st = env.status(r["request_id"], wait_seconds=10)
    assert st["status"] == "declined" and st["decline_reason"] == "wrong rate"
    assert not pdf_file.with_name("contract - signed.pdf").exists()
    r2 = env.request(pdf_path=str(pdf_file))
    port = env.sessions[r2["request_id"]].server.port
    assert env.cancel(r2["request_id"])["status"] == "cancelled"
    assert wait_closed(port)


def test_validation(env, client, pdf_file, tmp_path):
    from gotoquill.core import SignError
    bad = tmp_path / "x.pdf"
    bad.write_bytes(b"hello")
    for kw in ({"pdf_path": str(bad)}, {"pdf_path": str(tmp_path / "missing.pdf")},
               {"pdf_path": str(pdf_file), "placements": [{"page": 9, "x": 1, "y": 1}]},
               {"pdf_path": str(pdf_file), "placements": [{"field_name": "Nope"}]}):
        with pytest.raises(SignError):
            env.request(serve=False, **kw)
    r = env.request(pdf_path=str(pdf_file), serve=False)
    tok = env.sessions[r["request_id"]].sign_token
    assert client.get("/s/not-a-real-token/info").status_code == 404
    assert client.post(f"/s/{tok}/submit", json=sign_body(consent=False)).status_code == 400
    png = base64.b64encode(b"GIF89a....").decode()
    assert client.post(f"/s/{tok}/submit", json=sign_body(signature_png_base64=png)).status_code == 400
    # DNS-rebinding guard
    assert client.get(f"/s/{tok}/info", headers={"Host": "evil.example.com"}).status_code == 403


def test_size_limit(env, pdf_file):
    from gotoquill import core
    core.get_service().s.max_pdf_bytes = 1000
    with pytest.raises(core.SignError, match="too large"):
        env.request(pdf_path=str(pdf_file), serve=False)


def test_function_schema_and_python_api(env, pdf_file):
    from gotoquill import tools
    fns = json.loads((ROOT / "schemas" / "functions.json").read_text())
    names = {f["function"]["name"] for f in fns}
    assert names == {"request_signature", "get_signature_status", "wait_for_signature", "connect_notifications", "cancel_request", "apply_signature_response"} == set(tools._DISPATCH)
    assert tools.FUNCTIONS == fns
    r = tools.call("request_signature", json.dumps({"pdf_path": str(pdf_file), "open_browser": False, "delivery": "page"}))
    assert r["sign_url"].startswith("http://127.0.0.1:")
    assert tools.call("get_signature_status", {"request_id": r["request_id"]})["status"] == "pending"
    assert tools.call("cancel_request", {"request_id": r["request_id"]})["status"] == "cancelled"
    assert tools.call("get_signature_status", {"request_id": "nope"})["code"] == 404
    assert "error" in tools.call("nope", {})


def test_footer_toggle(env, client, pdf_file):
    from gotoquill import core
    r = env.request(pdf_path=str(pdf_file), serve=False)
    tok = env.sessions[r["request_id"]].sign_token
    assert client.get(f"/s/{tok}/info").json()["show_footer"] is True
    core.get_service().s.show_footer = False
    assert client.get(f"/s/{tok}/info").json()["show_footer"] is False


def _mcp_call(srv):
    async def call(name, args):
        res = await srv.call_tool(name, args)
        if isinstance(res, tuple):
            res = res[1] if isinstance(res[1], dict) else res[0]
        if isinstance(res, dict):
            return res.get("result", res)
        sc = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None)
        if sc:
            return sc.get("result", sc)
        return json.loads(res.content[0].text if hasattr(res, "content") else res[0].text)
    return call


def test_mcp_tools_and_ui_resource(env, pdf_file):
    import anyio

    from gotoquill.mcp_server import UI_MIME, UI_URI, build_server
    srv = build_server()
    call = _mcp_call(srv)

    async def flow():
        tools = {t.name: t for t in await srv.list_tools()}
        assert set(tools) == {"request_signature", "sign_pdf", "get_signature_status", "wait_for_signature", "connect_notifications", "cancel_request", "apply_signature_response",
                              "ui_load_document", "ui_submit_signature", "ui_delete_saved_signature"}
        meta = tools["request_signature"].meta or {}
        assert meta["ui"]["resourceUri"] == UI_URI
        assert tools["ui_submit_signature"].meta["ui"]["visibility"] == ["app"]
        contents = list(await srv.read_resource(UI_URI))
        c = contents[0]
        assert getattr(c, "mime_type", None) == UI_MIME
        html = c.content if hasattr(c, "content") else c.text
        assert "MODE = 'mcp-app'" in html and "ui/initialize" in html

        req = await call("request_signature", {"pdf_path": str(pdf_file), "signer_name": "Alex Example",
                                               "open_browser": False, "delivery": "page"})
        assert req["sign_url"].startswith("http://127.0.0.1:") and req["sign_token"], req
        assert httpx.post(req["sign_url"] + "/submit", json=sign_body()).status_code == 200
        st = await call("get_signature_status", {"request_id": req["request_id"], "wait_seconds": 10})
        assert st["status"] == "completed" and Path(st["output_path"]).exists()
        assert (await call("get_signature_status", {"request_id": "x"}))["code"] == 404
        bad = await call("wait_for_signature", {"request_id": "<request_id>", "wait_seconds": 0})
        # placeholder ids now resolve to the latest real request (with a note naming it)
        assert bad["request_id"] == req["request_id"] and req["request_id"] in bad["note"], bad
        unk = await call("wait_for_signature", {"request_id": "abc123", "wait_seconds": 0})
        assert unk["code"] == 404 and unk["recent_request_ids"] == [req["request_id"]]
        assert f"request_id='{req['request_id']}'" in unk["next"]

        # in-chat (MCP Apps) path: load + submit through app-only tools, no HTTP
        req2 = await call("request_signature", {"pdf_path": str(pdf_file), "open_browser": False, "delivery": "page",
                                                "output_path": str(pdf_file.with_name("chat.pdf"))})
        view = await call("ui_load_document", {"sign_token": req2["sign_token"]})
        assert view["pages"][0].startswith("data:image/png;base64,") and view["status"] == "pending"
        b = sign_body()
        assert (await call("ui_submit_signature", {"sign_token": req2["sign_token"], **b}))["status"] == "signed"
        st2 = await call("get_signature_status", {"request_id": req2["request_id"], "wait_seconds": 10})
        assert st2["status"] == "completed" and st2["audit"]["ip"] == "mcp-app"
        assert pdf_file.with_name("chat.pdf").exists()

    anyio.run(flow)


def test_cli_sign(env, pdf_file, capsys):
    from gotoquill import cli

    def signer():
        for _ in range(200):
            if env.sessions:
                s = next(iter(env.sessions.values()))
                if s.sign_url:
                    httpx.post(s.sign_url + "/submit", json=sign_body())
                    return
            time.sleep(0.05)
    threading.Thread(target=signer, daemon=True).start()
    with pytest.raises(SystemExit) as e:
        cli.main(["sign", str(pdf_file), "--no-browser", "--timeout", "20"])
    assert e.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "completed" and Path(out["output_path"]).exists()


def test_date_line_avoids_existing_text(sample_pdf):
    from datetime import datetime, timezone
    from gotoquill import pdf
    out = pdf.stamp(sample_pdf, [{"field_name": "ContractorSignature", "add_date": True}], sig_png(),
                    datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc), "X", "rid")
    with Opened(out) as d:
        p = d[0]
        hits = p.search_for("Signed 02/01/2026, 03:04 (UTC)")
        label = p.search_for("Contractor signature")[0]
        assert hits and label
        assert not hits[0].intersects(label)


def test_mcp_unknown_id_in_parallel_points_to_real_request(env, pdf_file):
    """Small models fire wait_for_signature alongside request_signature with a placeholder id; the 404 should
    wait for the in-flight request and name its real request_id."""
    import anyio

    from gotoquill.mcp_server import build_server
    srv = build_server()
    call = _mcp_call(srv)
    out: dict = {}

    async def flow():
        async def req():
            out["req"] = await call("request_signature", {"pdf_path": str(pdf_file), "open_browser": False,
                                                          "delivery": "page"})

        async def bad():
            out["bad"] = await call("wait_for_signature", {"request_id": "<request_id>", "wait_seconds": 0})
        async with anyio.create_task_group() as tg:
            tg.start_soon(bad)
            tg.start_soon(req)
        assert out["bad"]["request_id"] == out["req"]["request_id"], out["bad"]
        assert out["req"]["request_id"] in out["bad"]["note"]
        await call("cancel_request", {"request_id": out["req"]["request_id"]})

    anyio.run(flow)
