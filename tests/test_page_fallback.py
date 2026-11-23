"""Hosted signing page reachability check and fallback to the self-contained sign.html (network mocked)."""
import json
import urllib.error
from pathlib import Path

import pytest

from gotoquill import relay


class _Resp:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture()
def net(monkeypatch):
    """Turn the page check on and route urlopen through a fake; returns the list of calls."""
    monkeypatch.setenv("GOTOQUILL_PAGE_CHECK", "1")
    relay._PAGE_OK.clear()
    state = {"result": 200, "calls": []}

    def fake(req, timeout=None):
        state["calls"].append((req.get_method(), req.full_url, timeout))
        res = state["result"]
        if isinstance(res, Exception):
            raise res
        if isinstance(res, int) and res >= 400:
            raise urllib.error.HTTPError(req.full_url, res, "x", {}, None)
        return _Resp(res)

    monkeypatch.setattr(relay.urllib.request, "urlopen", fake)
    yield state
    relay._PAGE_OK.clear()


def test_page_base_env_and_trailing_slash(monkeypatch):
    monkeypatch.setenv("GOTOQUILL_PAGE_BASE", "https://fork.example/sign")
    assert relay.page_url() == "https://fork.example/sign/"
    monkeypatch.delenv("GOTOQUILL_PAGE_BASE")
    assert relay.page_url() == "https://pages.test/gotoquill/"  # legacy GOTOQUILL_PAGE_URL still works
    monkeypatch.delenv("GOTOQUILL_PAGE_URL")
    assert relay.page_url() == relay.DEFAULT_PAGE_URL


def test_reachable_is_cached_and_uses_short_timeout(net):
    assert relay.page_reachable("https://a.test/") is True
    assert relay.page_reachable("https://a.test/") is True
    assert len(net["calls"]) == 1 and net["calls"][0][0] == "HEAD" and net["calls"][0][2] <= 5


@pytest.mark.parametrize("res", [404, urllib.error.URLError("dns"), TimeoutError()])
def test_unreachable(net, res):
    net["result"] = res
    assert relay.page_reachable("https://b.test/") is False


def test_head_405_retries_with_get(net, monkeypatch):
    seq = iter([405, 200])

    def fake(req, timeout=None):
        net["calls"].append(req.get_method())
        code = next(seq)
        if code >= 400:
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        return _Resp(code)
    monkeypatch.setattr(relay.urllib.request, "urlopen", fake)
    assert relay.page_reachable("https://c.test/") is True and net["calls"] == ["HEAD", "GET"]


def test_link_falls_back_to_html_file_when_page_404(env, pdf_file, net):
    from gotoquill import sealed
    net["result"] = 404
    r = sealed.create_sealed_request(pdf_path=str(pdf_file))
    assert r["sign_url"] is None and r["link_fallback"] is True
    hp = Path(r["html_path"])
    assert hp.exists() and "<script>" in hp.read_text()
    assert hp.name in r["next"] and "do NOT send a link" in r["next"] and "pages.test" in r["warning"]


def test_link_kept_when_page_up(env, pdf_file, net):
    from gotoquill import sealed
    r = sealed.create_sealed_request(pdf_path=str(pdf_file))
    assert r["sign_url"].startswith("https://pages.test/gotoquill/#") and not r.get("link_fallback")
    assert not r.get("html_path")


def test_mcp_link_fallback(env, pdf_file, net):
    import anyio
    from gotoquill.mcp_server import build_server
    net["result"] = urllib.error.URLError("offline")

    async def go():
        return await build_server().call_tool("request_signature", {"pdf_path": str(pdf_file)})
    txt = json.dumps(anyio.run(go), default=str)
    assert "link_fallback" in txt and "sign.html" in txt


def test_static_page_assets_and_default_base():
    root = Path(__file__).resolve().parents[1]
    assert (root / "web/index.html").exists() and (root / "web/sign.js").exists()
    # default base is the Pages project root, which serves web/index.html
    assert relay.DEFAULT_PAGE_URL == "https://example.github.io/gotoquill/"
