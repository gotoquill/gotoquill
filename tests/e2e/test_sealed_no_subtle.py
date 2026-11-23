"""Sealed link/file in pages WITHOUT crypto.subtle (in-app HTML previews, http://LAN-IP origins), against the
REAL ntfy.sh relay. Opt-in: GOTOQUILL_REAL_RELAY=1 (needs network + Chrome). Also: blocked fetch / no RNG messages."""
import functools, http.server, os, shutil, socket, threading
from pathlib import Path
import pytest
from gotoquill import relay, tools

pw = pytest.importorskip("playwright.sync_api")
CHROME = shutil.which("google-chrome") or "/usr/bin/google-chrome"
pytestmark = [pytest.mark.skipif(not os.path.exists(CHROME), reason="no chrome"),
              pytest.mark.skipif(os.environ.get("GOTOQUILL_REAL_RELAY") != "1", reason="set GOTOQUILL_REAL_RELAY=1")]
WEB = Path(__file__).resolve().parents[2] / "web"
NO_SUBTLE = "Object.defineProperty(window.crypto, 'subtle', {value: undefined, configurable: true}); window.__noSubtle = !window.crypto.subtle;"


@pytest.fixture()
def real(fake_relay):
    relay.set_relay(None)  # real ntfy.sh
    yield


def _lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(("10.255.255.255", 1)); return s.getsockname()[0]
    except OSError: return "127.0.0.1"
    finally: s.close()


def _browser(p, init=None):
    b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
    if init: ctx.add_init_script(init)
    return b, ctx


def _sign(pg, url, errs):
    pg.on("pageerror", lambda e: errs.append(e)); pg.goto(url)
    pg.wait_for_selector("#app:not(.hidden), #closed:not(.hidden)", timeout=60000)
    assert pg.is_visible("#app"), pg.text_content("#closed")
    pg.click("#heroOpen"); pg.wait_for_selector("#heroSheet #tabType", state="visible"); pg.click("#tabType"); pg.fill("#typed", "Alex Example"); pg.check("#consent"); pg.click("#submit")
    pg.wait_for_selector("#done:not(.hidden)", timeout=60000)


def test_sealed_file_without_subtle_real_ntfy(env, pdf_file, real):
    r = tools.request_signature(str(pdf_file), delivery="link-file", signer_name="Alex Example", expires_in_minutes=15)
    with pw.sync_playwright() as p:
        b, ctx = _browser(p, NO_SUBTLE); pg = ctx.new_page(); errs = []
        _sign(pg, "file://" + r["html_path"], errs)
        assert pg.evaluate("window.__noSubtle") and pg.evaluate("!crypto.subtle") and not errs; b.close()
    st = tools.get_signature_status(r["request_id"], wait_seconds=30)
    assert st["status"] == "completed", st


@pytest.mark.parametrize("subtle", [False, True])
def test_link_on_insecure_lan_origin_real_ntfy(env, pdf_file, real, monkeypatch, subtle):
    ip = _lan_ip()
    srv = http.server.ThreadingHTTPServer((ip, 0), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(WEB)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("GOTOQUILL_PAGE_URL", f"http://{ip}:{srv.server_port}/index.html")
    try:
        r = tools.request_signature(str(pdf_file), signer_name="Alex Example", expires_in_minutes=15)
        assert r["sign_url"].startswith(f"http://{ip}:")
        with pw.sync_playwright() as p:
            b, ctx = _browser(p, None if subtle else NO_SUBTLE); pg = ctx.new_page(); errs = []
            _sign(pg, r["sign_url"], errs)
            if ip != "127.0.0.1": assert pg.evaluate("!window.isSecureContext")
            assert not errs; b.close()
        st = tools.get_signature_status(r["request_id"], wait_seconds=30)
        assert st["status"] == "completed", st
    finally:
        srv.shutdown()


def test_blocked_fetch_and_missing_rng_messages(env, pdf_file, real):
    r = tools.request_signature(str(pdf_file), delivery="link-file", expires_in_minutes=5)
    with pw.sync_playwright() as p:
        b, ctx = _browser(p, NO_SUBTLE); ctx.route("**/*", lambda rt: rt.abort() if rt.request.url.startswith("http") else rt.continue_())
        pg = ctx.new_page(); pg.goto("file://" + r["html_path"]); pg.wait_for_selector("#closed:not(.hidden)", timeout=30000)
        assert "tap Download, then open it in Chrome/Safari" in pg.text_content("#closedText")
        b.close()
        b, ctx = _browser(p, NO_SUBTLE + "Object.defineProperty(window.crypto, 'getRandomValues', {value: undefined, configurable: true});")
        pg = ctx.new_page(); pg.goto("file://" + r["html_path"]); pg.wait_for_selector("#closed:not(.hidden)", timeout=30000)
        assert "Tap Download" in pg.text_content("#closedText") and "Chrome" in pg.text_content("#closedText")
        b.close()
    tools.cancel_request(r["request_id"])
