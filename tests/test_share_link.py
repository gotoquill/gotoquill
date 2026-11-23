import hashlib
import json
from urllib.parse import urlparse

import httpx
import pytest

from test_flow import sign_body, wait_closed

HOST = "brave-quiet-otter-lake.trycloudflare.com"


class FakeTunnel:
    instances: list["FakeTunnel"] = []

    def __init__(self, port):
        self.port, self.hostname, self.running = port, HOST, False
        FakeTunnel.instances.append(self)

    def start(self):
        self.running = True
        return f"https://{HOST}"

    def stop(self):
        self.running = False


@pytest.fixture()
def fake_tunnel(monkeypatch):
    from gotoquill import tunnel
    FakeTunnel.instances.clear()
    monkeypatch.setattr(tunnel, "tunnel_factory", FakeTunnel)
    return FakeTunnel


def _via_tunnel(local_url, path="", method="get", **kw):
    """Simulate a request arriving through the tunnel: Host header = tunnel hostname."""
    return getattr(httpx, method)(local_url + path, headers={"Host": HOST, **kw.pop("headers", {})}, **kw)


def test_share_link_flow(env, pdf_file, fake_tunnel):
    r = env.request(pdf_path=str(pdf_file), share_link=True)
    assert r["share_link"] and r["sign_url"].startswith(f"https://{HOST}/s/")
    assert r["local_url"].startswith("http://127.0.0.1:")
    assert r["browser_opened"] is False
    t = fake_tunnel.instances[0]
    assert t.running and t.port == urlparse(r["local_url"]).port
    local = r["local_url"]
    assert _via_tunnel(local).status_code == 200
    assert httpx.get(local, headers={"Host": "evil.trycloudflare.com"}).status_code == 403
    assert _via_tunnel(local, "/submit", "post", json=sign_body()).json() == {"status": "signed"}
    res = env.wait(r["request_id"], 10)
    assert res["status"] == "completed"
    assert res["audit"]["delivery"] == "share link via tunnel"
    assert json.loads(open(res["audit_path"]).read())["delivery"] == "share link via tunnel"
    assert not t.running and wait_closed(urlparse(local).port)


def test_share_link_shorter_expiry_and_cancel_stops_tunnel(env, pdf_file, fake_tunnel):
    from datetime import datetime, timezone
    r = env.request(pdf_path=str(pdf_file), share_link=True)
    left = datetime.fromisoformat(r["expires_at"].replace("Z", "+00:00")) - datetime.now(timezone.utc)
    assert 14 * 60 < left.total_seconds() <= 15 * 60 + 5
    assert env.cancel(r["request_id"])["status"] == "cancelled"
    assert not fake_tunnel.instances[0].running


def test_tunnel_host_only_for_its_own_request(env, pdf_file, fake_tunnel):
    plain = env.request(pdf_path=str(pdf_file), open_browser=False)
    assert plain["share_link"] is False and plain["sign_url"] == plain["local_url"]
    assert _via_tunnel(plain["local_url"]).status_code == 403  # tunnel host not allowed on a normal page
    audit_delivery = env.sessions[plain["request_id"]]
    env.cancel(plain["request_id"])
    assert not fake_tunnel.instances and audit_delivery


def test_attempt_limit_locks_link(env, pdf_file, fake_tunnel):
    from gotoquill.config import get_settings
    get_settings().share_max_bad_attempts = 3
    r = env.request(pdf_path=str(pdf_file), share_link=True)
    base = r["local_url"].rsplit("/s/", 1)[0]
    for i in range(3):
        assert _via_tunnel(base, f"/s/wrongtoken{i}/info").status_code == 404
    assert _via_tunnel(r["local_url"]).status_code == 429  # even the right token is now locked
    env.cancel(r["request_id"])


def test_failed_submits_lock(env, pdf_file, fake_tunnel):
    r = env.request(pdf_path=str(pdf_file), share_link=True)
    for _ in range(5):
        assert _via_tunnel(r["local_url"], "/submit", "post", json=sign_body(consent=False)).status_code == 400
    assert _via_tunnel(r["local_url"], "/submit", "post", json=sign_body()).status_code == 429
    env.cancel(r["request_id"])


def test_tunnel_failure_gives_clear_error(env, pdf_file, monkeypatch):
    from gotoquill import tunnel
    from gotoquill.core import SignError

    class Broken(FakeTunnel):
        def start(self):
            raise tunnel.TunnelError("cloudflared gave no public URL (test)")
    monkeypatch.setattr(tunnel, "tunnel_factory", Broken)
    with pytest.raises(SignError) as e:
        env.request(pdf_path=str(pdf_file), share_link=True)
    assert "phone link" in str(e.value) and "without share_link" in str(e.value)


def test_env_var_turns_share_link_on(env, pdf_file, fake_tunnel, monkeypatch):
    from gotoquill.config import Settings
    monkeypatch.setenv("GOTOQUILL_SHARE_LINK", "1")
    assert Settings().share_link is True
    from gotoquill.config import get_settings
    get_settings().share_link = True
    r = env.request(pdf_path=str(pdf_file))
    assert r["share_link"] and r["sign_url"].startswith("https://")
    env.cancel(r["request_id"])


def test_download_verifies_checksum(tmp_path, monkeypatch):
    from gotoquill import tunnel
    monkeypatch.setattr(tunnel.sys, "platform", "linux")
    monkeypatch.setattr(tunnel.platform, "machine", lambda: "x86_64")
    blob = b"#!/bin/sh\necho fake\n"
    good = hashlib.sha256(blob).hexdigest()

    def fetch(digest):
        def f(url, timeout=60):
            if url.startswith("https://api.github.com/repos/cloudflare/cloudflared/releases/latest"):
                return json.dumps({"tag_name": "2099.1.1", "assets": [
                    {"name": "cloudflared-linux-amd64", "digest": "sha256:" + digest}]}).encode()
            assert url == "https://github.com/cloudflare/cloudflared/releases/download/2099.1.1/cloudflared-linux-amd64"
            return blob
        return f

    p = tunnel.download_cloudflared(tmp_path, fetch=fetch(good))
    assert p.read_bytes() == blob and p.stat().st_mode & 0o100
    with pytest.raises(tunnel.TunnelError, match="checksum mismatch"):
        tunnel.download_cloudflared(tmp_path / "x", fetch=fetch("0" * 64))
    # fallback: checksum listed in the release notes body
    assert tunnel.expected_sha256({"body": f"cloudflared-linux-amd64: {good}\n"}, "cloudflared-linux-amd64") == good


def test_url_parsing():
    from gotoquill.tunnel import URL_RE
    line = "2026-10-25T22:00:00Z INF |  https://brave-quiet-otter-lake.trycloudflare.com                    |"
    assert URL_RE.search(line).group(1) == HOST
