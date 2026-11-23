"""Unit tests for remote MCP HTTP transport, OAuth, and cloud PDF I/O."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import urllib.parse
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from gotoquill import cloud_io
from gotoquill.mcp_http import create_http_app
from gotoquill.mcp_oauth import OAuthStore, load_or_create_pairing_code


MIN_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


@pytest.fixture()
def remote_env(tmp_path, monkeypatch):
    monkeypatch.setenv("GOTOQUILL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("GOTOQUILL_CONFIG_DIR", str(tmp_path / "cfg"))
    cloud_io.reset_downloads()
    cloud_io.set_http_public_base(None)
    yield tmp_path
    cloud_io.reset_downloads()
    cloud_io.set_http_public_base(None)


@pytest.fixture()
def app_client(remote_env):
    app, code, created = create_http_app(public_base="http://testserver")
    assert created
    with TestClient(app) as client:
        yield client, code, app


def test_pairing_code_persisted_0600(remote_env):
    code, created = load_or_create_pairing_code()
    assert created and code
    path = remote_env / "cfg" / "remote-mcp" / "pairing.json"
    assert path.is_file()
    assert (path.stat().st_mode & 0o777) == 0o600
    code2, created2 = load_or_create_pairing_code()
    assert not created2 and code2 == code


def test_healthz_and_mcp_requires_bearer(app_client):
    client, code, _ = app_client
    assert client.get("/healthz").json()["status"] == "ok"
    r = client.get("/mcp")
    assert r.status_code == 401
    assert "resource_metadata" in r.headers.get("www-authenticate", "")
    # wrong token
    r = client.get("/mcp", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_oauth_metadata(app_client):
    client, _, _ = app_client
    prm = client.get("/.well-known/oauth-protected-resource").json()
    assert prm["resource"].endswith("/mcp")
    assert "authorization_servers" in prm
    asmeta = client.get("/.well-known/oauth-authorization-server").json()
    assert asmeta["authorization_endpoint"].endswith("/authorize")
    assert asmeta["registration_endpoint"].endswith("/register")
    assert "S256" in asmeta["code_challenge_methods_supported"]


def _oauth_token(client, pairing_code: str) -> str:
    reg = client.post("/register", json={
        "client_name": "pytest",
        "redirect_uris": ["http://127.0.0.1:9/cb"],
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    })
    assert reg.status_code == 201
    client_id = reg.json()["client_id"]
    redirect = "http://127.0.0.1:9/cb"
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert client.get("/authorize", params={
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s",
        "resource": "http://testserver/mcp",
    }).status_code == 200
    r = client.post("/authorize", data={
        "client_id": client_id, "redirect_uri": redirect, "response_type": "code",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "s",
        "resource": "http://testserver/mcp", "pairing_code": pairing_code,
    }, follow_redirects=False)
    assert r.status_code == 302
    code = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers["location"]).query)["code"][0]
    tok = client.post("/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": redirect,
        "client_id": client_id, "code_verifier": verifier,
    })
    assert tok.status_code == 200
    return tok.json()["access_token"]


def test_oauth_flow_and_mcp_initialize(app_client):
    client, pairing, _ = app_client
    access = _oauth_token(client, pairing)
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }
    r = client.post("/mcp", headers={
        "Authorization": f"Bearer {access}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }, content=json.dumps(init))
    assert r.status_code == 200
    body = r.json()
    assert body["result"]["serverInfo"]["name"] == "gotoquill" or "gotoquill" in json.dumps(body)


def test_pairing_code_as_bearer(app_client):
    client, code, _ = app_client
    init = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }
    r = client.post("/mcp", headers={
        "Authorization": f"Bearer {code}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }, content=json.dumps(init))
    assert r.status_code == 200


def test_cloud_io_materialize_and_download(app_client, remote_env):
    client, code, _ = app_client
    b64 = base64.b64encode(MIN_PDF).decode()
    path = cloud_io.materialize_pdf(pdf_base64=b64, document_name="demo.pdf")
    assert Path(path).is_file()
    assert Path(path).read_bytes().startswith(b"%PDF")

    cloud_io.set_http_public_base("http://testserver")
    meta = cloud_io.register_download(path, name="demo.signed.pdf")
    r = client.get(f"/download/{meta['token']}")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF")
    assert "demo.signed.pdf" in (r.headers.get("content-disposition") or "")

    # expired / missing
    assert client.get("/download/not-a-real-token").status_code == 404


def test_attach_cloud_result_adds_url(remote_env, tmp_path):
    cloud_io.set_http_public_base("https://example.trycloudflare.com")
    pdf = tmp_path / "out.signed.pdf"
    pdf.write_bytes(MIN_PDF)
    out = cloud_io.attach_cloud_result({"status": "completed", "signed_pdf_path": str(pdf)})
    assert out["signed_pdf_url"].startswith("https://example.trycloudflare.com/download/")
    assert out["signed_pdf_save_url"] == out["signed_pdf_url"] + "?save=1"
    assert "signed_pdf_base64" in out
    assert out["signed_pdf_sha256"] == hashlib.sha256(MIN_PDF).hexdigest()


def test_download_save_page_and_unicode_headers(app_client, tmp_path):
    client, _, _ = app_client
    path = tmp_path / "dana.pdf"
    path.write_bytes(MIN_PDF)
    name = "הסכם דנה-signed.pdf"
    meta = cloud_io.register_download(str(path), name=name)
    url = f"/download/{meta['token']}"
    for method in ("GET", "HEAD"):
        raw = client.request(method, url)
        assert raw.status_code == 200
        assert raw.headers["content-type"] == "application/pdf"
        assert raw.headers["content-length"] == str(len(MIN_PDF))
        assert raw.headers["content-disposition"] == (
            'attachment; filename="_ _-signed.pdf"; filename*=UTF-8\'\'' + urllib.parse.quote(name, safe=""))
        assert raw.headers["cache-control"] == "private, no-store"
        assert raw.headers["x-content-type-options"] == "nosniff"
        assert raw.content == (MIN_PDF if method == "GET" else b"")
        page = client.request(method, url + "?save=1")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        assert page.headers["cache-control"] == "private, no-store"
        assert page.headers["referrer-policy"] == "no-referrer"
        assert page.headers["x-content-type-options"] == "nosniff"
        assert page.headers["x-frame-options"] == "DENY"
        policy = page.headers["content-security-policy"]
        assert "default-src 'none'" in policy
        assert "connect-src 'self'" in policy
        assert "frame-ancestors 'none'" in policy
        assert "unsafe-inline" not in policy
        assert int(page.headers["content-length"]) > 0
        if method == "GET":
            assert int(page.headers["content-length"]) == len(page.content)
            assert name in page.text
            assert f'href="{url}"' in page.text
            assert "%PDF" not in page.text and "JVBER" not in page.text
        else:
            assert page.content == b""
    for candidate in ("missing", meta["token"][:-1], meta["token"] + "x"):
        for query in ("", "?save=1"):
            denied = client.get(f"/download/{candidate}{query}")
            assert denied.status_code == 404
            assert name not in denied.text and meta["token"] not in denied.text
            assert denied.headers["cache-control"] == "private, no-store"
    cloud_io.pop_download(meta["token"])["expires"] = 0
    for query in ("", "?save=1"):
        assert client.get(url + query).status_code == 404
    missing = cloud_io.register_download(str(path))
    path.unlink()
    assert client.get(f"/download/{missing['token']}?save=1").status_code == 404


def test_save_page_escapes_filename():
    from gotoquill.save_page import save_page, safe_filename, attachment_disposition
    name = safe_filename('דנה<script>\r\n&quot;__NONCE__.pdf')
    response = save_page('/download/dana_fixture', name)
    assert b'<script>' not in response.body
    assert b'&amp;quot;__NONCE__' in response.body
    header = attachment_disposition(name)
    assert "\r" not in header and "\n" not in header
    assert "filename*=UTF-8''" in header
