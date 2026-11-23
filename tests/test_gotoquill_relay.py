"""End-to-end: sealed-link flow against the local Python gotoquill relay (Starlette)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sys
import threading
import time
from pathlib import Path
from urllib.parse import parse_qs

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay" / "python"))

from pdfmake import blank_png, image_count

from gotoquill import offline, relay, sealed, tools
from gotoquill_relay.app import _Store, create_app

PNG = base64.b64encode(blank_png(60, 20)).decode()


@pytest.fixture()
def agentsign_server(monkeypatch):
    """Live Starlette app on a background uvicorn thread; wire GotoquillRelay to it."""
    import uvicorn
    from gotoquill_relay import app as relay_mod

    store = _Store()
    app = create_app(store)
    # bind ephemeral port
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn failed to start"
    sock = server.servers[0].sockets[0]
    port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    monkeypatch.setenv("GOTOQUILL_RELAY_URL", base)
    monkeypatch.setenv("GOTOQUILL_RELAY_TYPE", "gotoquill")
    monkeypatch.setenv("GOTOQUILL_PAGE_CHECK", "0")
    r = relay.GotoquillRelay(base)
    relay.set_relay(r)
    yield {"base": base, "store": store, "relay": r}
    server.should_exit = True
    thread.join(timeout=5)
    relay.set_relay(None)


def _open_link_via_relay(url: str, r: relay.GotoquillRelay):
    frag = parse_qs(url.split("#", 1)[1])
    assert frag.get("rt") == ["gotoquill"]
    q, a, k = frag["q"][0], frag["a"][0], frag["k"][0]
    key = base64.urlsafe_b64decode(k + "=" * (-len(k) % 4))
    blobs = r.fetch(q)
    assert blobs, "request blob missing on gotoquill relay"
    payload = json.loads(relay.unseal(key, blobs[0], relay.aad("request", q)))
    return payload, key, a


def _reply(payload, key, reply_topic, r, decision="sign"):
    D = payload["data"]
    resp = {"type": "gotoquill-response", "version": 1, "request_id": D["request_id"],
            "original_sha256": D["original_sha256"], "client_timestamp": "", "decision": decision}
    if decision == "sign":
        resp.update(signature_png="data:image/png;base64," + PNG, method="drawn", typed_name="",
                    signer_name="Dana", consent=True, consent_text=D["consent_text"])
        sig = hashlib.sha256(base64.b64decode(PNG)).hexdigest()
        msg = offline.proof_message(resp["request_id"], D["original_sha256"], sig, "drawn", "", "Dana", "")
        resp["proof"] = hmac.new(bytes.fromhex(D["key"]), msg.encode(), hashlib.sha256).hexdigest()
    blob = relay.seal(key, json.dumps(resp).encode(), relay.aad("reply", reply_topic))
    r.publish(reply_topic, blob)


def test_relay_api_put_get_delete_and_ttl(agentsign_server):
    import urllib.error
    import urllib.request
    base = agentsign_server["base"]
    topic = relay.new_topic_128()
    body = b"\x00ciphertext-only\xff" * 20
    req = urllib.request.Request(f"{base}/v1/box/{topic}", data=body, method="PUT",
                                 headers={"Content-Type": "application/octet-stream", "X-TTL-Seconds": "120"})
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 201
    # HEAD exists
    head = urllib.request.Request(f"{base}/v1/box/{topic}", method="HEAD")
    with urllib.request.urlopen(head) as resp:
        assert resp.status == 200
    with urllib.request.urlopen(f"{base}/v1/box/{topic}") as resp:
        assert resp.read() == body
    # delete-on-read
    try:
        urllib.request.urlopen(f"{base}/v1/box/{topic}")
        assert False, "expected 404"
    except urllib.error.HTTPError as e:
        assert e.code == 404


def test_relay_rejects_oversize_and_bad_topic(agentsign_server):
    import urllib.error
    import urllib.request
    base = agentsign_server["base"]
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{base}/v1/box/short", data=b"x", method="PUT"))
        assert False
    except urllib.error.HTTPError as e:
        assert e.code in (400, 404)
    big = b"x" * (2 * 1024 * 1024 + 10)
    try:
        urllib.request.urlopen(urllib.request.Request(
            f"{base}/v1/box/{relay.new_topic()}", data=big, method="PUT"))
        assert False
    except urllib.error.HTTPError as e:
        assert e.code == 413


def test_sealed_e2e_against_agentsign_relay(env, pdf_file, agentsign_server, monkeypatch):
    monkeypatch.setenv("GOTOQUILL_PAGE_URL", "https://pages.test/gotoquill/")
    r = tools.request_signature(str(pdf_file), signer_name="Dana")
    assert r["delivery"].startswith("sealed link")
    assert "rt=gotoquill" in r["sign_url"]
    assert agentsign_server["base"] in r["sign_url"] or "r=" in r["sign_url"]
    # relay only has ciphertext
    store: _Store = agentsign_server["store"]
    for topic, (blob, _) in list(store._boxes.items()):
        assert b"%PDF" not in blob and b"Dana" not in blob and r["request_id"].encode() not in blob
    payload, key, a = _open_link_via_relay(r["sign_url"], agentsign_server["relay"])
    assert payload["document_sha256"] == hashlib.sha256(pdf_file.read_bytes()).hexdigest()
    _reply(payload, key, a, agentsign_server["relay"])
    st = tools.get_signature_status(r["request_id"], wait_seconds=10)
    assert st["status"] == "completed", st
    assert image_count(st["output_path"]) >= 1
    audit = json.loads(Path(st["audit_path"]).read_text())
    assert audit["proof"] == "hmac-sha256 verified"
    # second GET of reply is empty (consumed)
    assert agentsign_server["relay"].fetch(a) == []


def test_wait_poll_backoff_completes(env, pdf_file, agentsign_server, monkeypatch):
    monkeypatch.setenv("GOTOQUILL_PAGE_URL", "https://pages.test/gotoquill/")
    r = tools.request_signature(str(pdf_file), signer_name="Dana")
    payload, key, a = _open_link_via_relay(r["sign_url"], agentsign_server["relay"])

    def late_reply():
        time.sleep(1.5)
        _reply(payload, key, a, agentsign_server["relay"])

    threading.Thread(target=late_reply, daemon=True).start()
    st = tools.get_signature_status(r["request_id"], wait_seconds=30)
    assert st["status"] == "completed", st


def test_make_relay_type_detection(monkeypatch):
    monkeypatch.setenv("GOTOQUILL_RELAY_TYPE", "")
    monkeypatch.delenv("GOTOQUILL_RELAY_TYPE", raising=False)
    assert relay.relay_type("https://ntfy.sh") == "ntfy"
    assert relay.relay_type("https://gotoquill-relay.example.workers.dev") == "gotoquill"
    assert relay.relay_type("https://example.com/v1") == "gotoquill"
    monkeypatch.setenv("GOTOQUILL_RELAY_TYPE", "gotoquill")
    assert relay.relay_type("https://ntfy.sh") == "gotoquill"
    monkeypatch.setenv("GOTOQUILL_RELAY_TYPE", "ntfy")
    assert relay.relay_type("https://gotoquill-relay.x.workers.dev") == "ntfy"


def test_agentsign_max_payload(agentsign_server):
    r = agentsign_server["relay"]
    with pytest.raises(relay.RelayError):
        r.publish(relay.new_topic(), b"x" * (2 * 1024 * 1024 + 1))


def test_health_and_root_return_demo_notice(agentsign_server):
    import urllib.request
    base = agentsign_server["base"]
    for path in ("/", "/health"):
        with urllib.request.urlopen(f"{base}{path}") as resp:
            body = json.loads(resp.read().decode())
        assert body.get("ok") is True
        assert body.get("demo") is True
        notice = body.get("notice") or ""
        assert "demo / for testing only" in notice
        assert "deploy your own for production" in notice
        assert "uptime" in notice.lower()
        limits = body.get("limits") or {}
        assert limits.get("max_bytes") == 1 * 1024 * 1024
        assert limits.get("default_ttl_seconds") == 3600
        assert limits.get("max_ttl_seconds") == 24 * 3600
        assert "abuse" in body


def test_cloud_mode_requires_explicit_relay_url(monkeypatch):
    monkeypatch.delenv("GOTOQUILL_RELAY_TYPE", raising=False)
    monkeypatch.delenv("GOTOQUILL_RELAY_URL", raising=False)
    monkeypatch.delenv("GOTOQUILL_RELAY", raising=False)
    monkeypatch.setenv("GOTOQUILL_CLOUD", "1")
    assert relay.cloud_mode() is True
    assert relay.relay_type() == "gotoquill"
    with pytest.raises(relay.RelayError) as ei:
        relay.relay_url()
    msg = str(ei.value)
    assert "GOTOQUILL_RELAY_URL" in msg
    assert "deploy.sh" in msg
    assert "Deploy to Cloudflare" in msg or "relay/README" in msg
    assert "no shared public relay" in msg.lower() or "There is no shared public relay" in msg
    monkeypatch.setenv("GOTOQUILL_RELAY_URL", "https://gotoquill-relay.example.workers.dev")
    assert relay.relay_url() == "https://gotoquill-relay.example.workers.dev"
    monkeypatch.delenv("GOTOQUILL_RELAY_URL", raising=False)
    monkeypatch.setenv("GOTOQUILL_CLOUD", "0")
    monkeypatch.delenv("GOTOQUILL_RELAY_TYPE", raising=False)
    assert relay.relay_type() == "ntfy"
    assert relay.relay_url() == relay.DEFAULT_RELAY_URL


def test_agentsign_type_without_url_errors(monkeypatch):
    monkeypatch.delenv("GOTOQUILL_RELAY_URL", raising=False)
    monkeypatch.delenv("GOTOQUILL_RELAY", raising=False)
    monkeypatch.setenv("GOTOQUILL_CLOUD", "0")
    monkeypatch.setenv("GOTOQUILL_RELAY_TYPE", "gotoquill")
    with pytest.raises(relay.RelayError) as ei:
        relay.make_relay()
    assert "deploy.sh" in str(ei.value)


def test_accepts_exactly_one_mib(agentsign_server):
    import urllib.request
    base = agentsign_server["base"]
    topic = relay.new_topic()
    body = b"y" * (1 * 1024 * 1024)
    with urllib.request.urlopen(urllib.request.Request(
            f"{base}/v1/box/{topic}", data=body, method="PUT")) as resp:
        assert resp.status in (200, 201, 204)
    with urllib.request.urlopen(f"{base}/v1/box/{topic}") as resp:
        assert resp.read() == body


def test_poll_backoff_schedule():
    """Empty polls should back off from ~5s toward 30s+ (free-tier friendly)."""
    delays = [min(45.0, 5.0 * (1.5 ** min(a, 8))) for a in range(10)]
    assert delays[0] == 5.0
    assert delays[1] == 7.5
    assert delays[4] >= 25.0
    assert delays[-1] == 45.0
    assert all(d >= 5.0 for d in delays)


def test_agentsign_fetch_uses_head_first(agentsign_server, monkeypatch):
    """Empty fetch must HEAD before GET so polling does not burn delete-on-read GETs."""
    import urllib.request as ur
    r = agentsign_server["relay"]
    topic = relay.new_topic()
    calls = []
    real_urlopen = ur.urlopen

    def wrapped(req, *a, **kw):
        calls.append(req.get_method())
        return real_urlopen(req, *a, **kw)

    monkeypatch.setattr(ur, "urlopen", wrapped)
    assert r.fetch(topic) == []
    assert calls and calls[0] == "HEAD"
    assert "GET" not in calls  # HEAD 404 → empty without GET
