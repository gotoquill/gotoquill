"""Getting told when it's signed: `gotoquill wait` exit codes, completion hooks (once), webhook, MCP resource."""
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from gotoquill import cli, notify, offline, tools
from test_sealed import open_link, reply


def _wait(rid, *extra):
    with pytest.raises(SystemExit) as e:
        cli.main(["wait", rid, *extra])
    return e.value.code


def _sealed(pdf_file, **kw):
    return tools.request_signature(str(pdf_file), signer_name="Dana", **kw)


def test_request_next_tells_agent_to_wait_in_a_way_that_wakes_it(env, pdf_file):
    r = _sealed(pdf_file)
    assert r["wait_command"] == f"gotoquill wait {r['request_id']}"
    n = r["next"]
    assert "IMMEDIATELY" in n and f"gotoquill wait {r['request_id']}" in n and "wait_seconds=600" in n
    assert "never end your turn" in n and n.index("gotoquill wait") < n.index("wait_seconds=600")


def test_wait_completed_exit_0_prints_status_with_next(env, pdf_file, fake_relay, capsys):
    r = _sealed(pdf_file)
    p, k, a = open_link(r["sign_url"], fake_relay)
    reply(p, k, a, fake_relay)
    assert _wait(r["request_id"], "--timeout", "5") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "completed" and os.path.isfile(out["signed_pdf_path"]) and "signed PDF" in out["next"]


def test_wait_declined_cancelled_expired_timeout_codes(env, pdf_file, fake_relay, capsys):
    r = _sealed(pdf_file)
    p, k, a = open_link(r["sign_url"], fake_relay)
    reply(p, k, a, fake_relay, decision="decline")
    assert _wait(r["request_id"], "--timeout", "5") == 3
    r = _sealed(pdf_file); tools.cancel_request(r["request_id"])
    assert _wait(r["request_id"], "--timeout", "5") == 5
    r = _sealed(pdf_file)
    d = offline._load(r["request_id"]); d["expires_at"] = "2000-01-01T00:00:00Z"; offline._store(d)
    assert _wait(r["request_id"], "--timeout", "5") == 4
    r = _sealed(pdf_file)
    assert _wait(r["request_id"], "--timeout", "0.3") == 6
    assert json.loads(capsys.readouterr().out.split("\n}\n")[-2] + "\n}")["timed_out"] is True
    assert _wait("req_0000000000000000", "--timeout", "1") == 2


def test_command_hook_fires_exactly_once_with_env_and_payload(env, pdf_file, fake_relay, tmp_path):
    log = tmp_path / "hook.log"
    cmd = (f'printf "%s|%s|%s|%s\\n" "$GOTOQUILL_STATUS" "$GOTOQUILL_REQUEST_ID" "$GOTOQUILL_SIGNED_PDF" '
           f'"$(cat)" >> "{log}"')
    r = _sealed(pdf_file, on_complete_command=cmd, watcher="none")
    assert r["hooks"]["command"] == cmd
    p, k, a = open_link(r["sign_url"], fake_relay)
    reply(p, k, a, fake_relay)
    st = tools.get_signature_status(r["request_id"], wait_seconds=3)
    assert st["status"] == "completed"
    tools.get_signature_status(r["request_id"])
    assert _wait(r["request_id"], "--timeout", "2") == 0
    lines = log.read_text().splitlines()
    assert len(lines) == 1, lines
    status, rid, pdf, payload = lines[0].split("|", 3)
    assert status == "completed" and rid == r["request_id"] and pdf == st["signed_pdf_path"] and os.path.isfile(pdf)
    assert json.loads(payload)["status"] == "completed"
    assert notify.maybe_fire(r["request_id"], st) is False  # guarded


def test_webhook_posted_once_by_background_watcher_without_any_polling(env, pdf_file, fake_relay):
    got = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            got.append((self.headers.get("X-Gotoquill-Status"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(204); self.end_headers()

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        r = _sealed(pdf_file, on_complete_webhook=f"http://127.0.0.1:{srv.server_port}/done", watcher="thread")
        assert r["watcher"]["mode"] == "thread"
        p, k, a = open_link(r["sign_url"], fake_relay)
        reply(p, k, a, fake_relay)
        end = time.time() + 20
        while not got and time.time() < end:  # the agent never calls status: the watcher must do it all
            time.sleep(0.2)
        time.sleep(0.5)
        assert len(got) == 1 and got[0][0] == "completed" and got[0][1]["request_id"] == r["request_id"]
        assert os.path.isfile(got[0][1]["signed_pdf_path"])  # stamped by the watcher before firing
    finally:
        srv.shutdown()


def test_bad_webhook_rejected(env, pdf_file):
    assert "error" in tools.call("request_signature", {"pdf_path": str(pdf_file), "on_complete_webhook": "file:///x"})


def test_mcp_request_resource_and_watcher(env, pdf_file, fake_relay, tmp_path):
    import anyio

    from gotoquill.mcp_server import build_server
    log = tmp_path / "mcp-hook.log"

    async def go():
        srv = build_server()
        templates = await srv.list_resource_templates()
        assert any("gotoquill://requests/{request_id}" in str(getattr(t, "uri_template", t)) for t in templates)
        from test_flow import _mcp_call
        r = await _mcp_call(srv)("request_signature", {"pdf_path": str(pdf_file),
                                                       "on_complete_command": f'echo "$GOTOQUILL_STATUS" >> "{log}"'})
        assert r["resource_uri"] == f"gotoquill://requests/{r['request_id']}" and r["watcher"]["mode"]
        body = await srv.read_resource(r["resource_uri"])
        txt = body[0].content if isinstance(body, list) else body.contents[0].text
        assert json.loads(txt)["status"] == "pending"
        p, k, a = open_link(r["sign_url"], fake_relay)
        reply(p, k, a, fake_relay)
        for _ in range(100):  # the server's own watcher task stamps it and fires the hook; nobody polls
            if log.exists():
                break
            await anyio.sleep(0.2)
        return r
    r = anyio.run(go)
    assert log.read_text().split() == ["completed"]
    assert offline.status(r["request_id"])["status"] == "completed"


def test_mcp_client_gets_resource_updated_and_log_when_signed(env, pdf_file, fake_relay):
    import anyio
    from mcp import Client

    from gotoquill.mcp_server import build_server
    seen = []

    async def on_msg(m):
        seen.append(m)

    async def on_log(p):
        seen.append(p)

    async def go():
        async with Client(build_server(), mode="legacy", message_handler=on_msg, logging_callback=on_log) as c:
            res = await c.call_tool("request_signature", {"pdf_path": str(pdf_file)})
            r = res.structured_content or json.loads(res.content[0].text)
            r = r.get("result", r)
            p, k, a = open_link(r["sign_url"], fake_relay)
            reply(p, k, a, fake_relay)
            for _ in range(100):
                if any("resources/updated" in repr(x) or "ResourceUpdated" in type(getattr(x, "root", x)).__name__
                       for x in seen):
                    break
                await anyio.sleep(0.2)
            return r
    r = anyio.run(go)
    blob = " ".join(repr(x) for x in seen)
    assert f"gotoquill://requests/{r['request_id']}" in blob, blob[:2000]
    assert "gotoquill request finished" in blob


def test_detached_watcher_process_and_wait_subprocess(env, pdf_file, tmp_path, monkeypatch):
    """Real processes: the detached watcher outlives the call and fires the hook; `gotoquill wait` exits 5."""
    import subprocess
    import sys
    monkeypatch.setenv("GOTOQUILL_RELAY_URL", "http://127.0.0.1:9")  # child processes never reach ntfy.sh
    log = tmp_path / "proc-hook.log"
    r = _sealed(pdf_file, on_complete_command=f'echo "$GOTOQUILL_STATUS" >> "{log}"')
    assert r["watcher"]["mode"] == "process" and r["watcher"]["pid"]
    tools.cancel_request(r["request_id"])
    p = subprocess.run([sys.executable, "-m", "gotoquill", "wait", r["request_id"], "--timeout", "10"],
                       capture_output=True, text=True, timeout=60, env=dict(os.environ))
    assert p.returncode == 5 and json.loads(p.stdout)["status"] == "cancelled"
    end = time.time() + 30
    while not log.exists() and time.time() < end:
        time.sleep(0.2)
    time.sleep(1)
    assert log.read_text().split() == ["cancelled"]
