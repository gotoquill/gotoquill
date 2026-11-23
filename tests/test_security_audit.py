"""Offline synthetic regressions for the November security review."""
import base64
import json
import socket
import zlib

import pytest

from gotoquill import cloud_io, offline
from gotoquill.core import SignError


@pytest.mark.parametrize("address", ["127.0.0.1", "10.1.2.3", "172.16.2.3", "192.168.0.1",
    "169.254.169.254", "100.64.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "224.0.0.1", "64:ff9b::a00:1", "2002:7f00:1::"])
def test_ssrf_rejects_private_dns_answers(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    with pytest.raises(SignError, match="public HTTPS"):
        cloud_io._public_destination("https://documents.example/sample.pdf")


def test_ssrf_rejects_mixed_dns_and_insecure_urls(monkeypatch):
    answers = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, 443)) for a in ["1.1.1.1", "127.0.0.1"]]
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: answers)
    for url in ["https://documents.example/a", "http://documents.example/a", "https://dana@documents.example/a",
                "https://documents.example:8443/a", "https://documents.example/a#credential"]:
        with pytest.raises(SignError):
            cloud_io._public_destination(url)


def test_redirects_validated_before_connect_and_hop_limit(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "",
        ("127.0.0.1" if host == "private.example" else "1.1.1.1", 443))])
    calls = []
    location = "https://private.example/metadata"
    class Reply:
        status = 302
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def getheader(self, name): return location
    class Connection:
        def __init__(self, host, ip): calls.append((host, ip))
        def request(self, *args, **kwargs): pass
        def getresponse(self): return Reply()
        def close(self): pass
    monkeypatch.setattr(cloud_io, "_PinnedHTTPSConnection", Connection)
    with pytest.raises(SignError, match="public HTTPS"):
        cloud_io._fetch_pdf_url("https://documents.example/sample.pdf")
    assert calls == [("documents.example", "1.1.1.1")]
    calls.clear()
    location = "/loop"
    with pytest.raises(SignError, match="redirect limit"):
        cloud_io._fetch_pdf_url("https://documents.example/sample.pdf")
    assert len(calls) == 4


def test_https_pins_ip_and_verifies_original_hostname(monkeypatch):
    connected, wrapped = [], []
    monkeypatch.setattr(socket, "create_connection", lambda addr, timeout: connected.append(addr) or object())
    class TLS:
        def wrap_socket(self, sock, server_hostname):
            wrapped.append(server_hostname)
            return sock
    connection = cloud_io._PinnedHTTPSConnection("documents.example", "1.1.1.1")
    connection._context = TLS()
    connection.connect()
    assert connected == [("1.1.1.1", 443)] and wrapped == ["documents.example"]


def code(raw):
    compressor = zlib.compressobj(wbits=-15)
    return "GOTOQUILL1Z." + base64.urlsafe_b64encode(compressor.compress(raw) + compressor.flush()).decode().rstrip("=")


def test_offline_expansion_limit_and_valid_compact_code():
    with pytest.raises(SignError, match="too large") as exc:
        offline.parse_response(code(b" " * (8 * 1024 * 1024 + 1)))
    assert exc.value.code == 413
    response = {"type": "gotoquill-response", "request_id": "req_sample", "decision": "decline"}
    assert offline.parse_response(code(json.dumps(response).encode())) == response
    damaged = code(json.dumps(response).encode())[:-5]
    with pytest.raises(SignError):
        offline.parse_response(damaged)
