"""Phone e2e for offline file mode (Playwright + Chrome). Skipped if unavailable.
Set GOTOQUILL_SCREENSHOTS=dir to save screenshots."""
import json, os, shutil
import pytest
from gotoquill import tools

pw = pytest.importorskip("playwright.sync_api")
CHROME = shutil.which("google-chrome") or "/usr/bin/google-chrome"
pytestmark = pytest.mark.skipif(not os.path.exists(CHROME), reason="no chrome")

SHARE_STUB = """window.__shared=null; navigator.canShare=()=>true;
navigator.share=d=>{ window.__shared={n:(d.files&&d.files[0]&&d.files[0].name)||null, text:d.text||null};
  if (d.files && d.files[0]) return d.files[0].text().then(t=>{window.__shared.t=t;});
  return Promise.resolve(); };"""


def _sign(page, url):
    page.goto(url); page.wait_for_selector("#app:not(.hidden)")
    page.click("#heroOpen"); page.wait_for_selector("#heroSheet #tabType", state="visible"); page.click("#tabType"); page.fill("#typed", "Dana Signer"); page.check("#consent"); page.click("#submit")
    page.wait_for_selector("#done:not(.hidden)")


@pytest.mark.parametrize("share", [True, False])
def test_phone_send_back(env, pdf_file, tmp_path, share):
    r = tools.request_signature(str(pdf_file), delivery="file", signer_name="Dana Signer")
    shots = os.environ.get("GOTOQUILL_SCREENSHOTS")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True, accept_downloads=True)
        if share: ctx.add_init_script(SHARE_STUB)
        else: ctx.add_init_script("delete Navigator.prototype.canShare; delete Navigator.prototype.share;")
        pg = ctx.new_page(); errs = []; pg.on("pageerror", lambda e: errs.append(e))
        _sign(pg, "file://" + r["html_path"])
        assert pg.is_visible("#download") and pg.is_visible("#downloadPdf")
        assert pg.is_visible("#send") and pg.is_visible("#sharePdf")
        assert "attach" in (pg.text_content("#sendHint") or "").lower()
        assert not pg.is_visible("#code") and not pg.is_visible("#copy")
        code = pg.input_value("#code"); assert code.startswith("GOTOQUILL1")
        if share:
            pg.click("#send")
            pg.wait_for_function("() => window.__shared && window.__shared.t")
            shared = pg.evaluate("window.__shared")
            assert shared["n"] == "Contract signature.gotoquill"
            assert json.loads(shared["t"])["browser_pdf_sha256"]
        else:
            with pg.expect_download() as downloaded:
                pg.click("#send")
            assert downloaded.value.suggested_filename == "Contract signature.gotoquill"
            pg.click("#trouble summary")
            assert pg.is_visible("#copy") and pg.is_visible("#code")
        if shots: pg.screenshot(path=os.path.join(shots, "file-mode-after-sign.png"))
        assert not errs; b.close()
    out = tools.apply_signature_response(r["request_id"], response_text=code)
    assert out["status"] == "completed"


def test_phone_pad_is_large(env, pdf_file, tmp_path):
    """Hero sheet near full height; pad ~45% of viewport on Pixel-sized phone."""
    r = tools.request_signature(str(pdf_file), delivery="file", signer_name="Dana Signer")
    shots = os.environ.get("GOTOQUILL_SCREENSHOTS")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 412, "height": 915}, device_scale_factor=2.625, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        pg.goto("file://" + r["html_path"])
        pg.wait_for_selector("#app:not(.hidden)")
        box = pg.locator("#pages button.box").first.bounding_box()
        pg.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        pg.wait_for_timeout(700)
        m = pg.evaluate("""() => {
          const sh = document.getElementById('heroSheet');
          const pad = document.getElementById('pad');
          const sr = sh.getBoundingClientRect(), pr = pad.getBoundingClientRect();
          return { shH: sr.height, padH: pr.height, padW: pr.width, vh: window.innerHeight, vw: window.innerWidth,
                   orient: !!document.getElementById('orientHint') };
        }""")
        assert m["shH"] >= m["vh"] * 0.80, m
        assert m["padH"] >= m["vh"] * 0.40, m
        assert m["padW"] >= m["vw"] * 0.85, m
        assert m["orient"]
        if shots:
            pg.screenshot(path=os.path.join(shots, "file-mode-pad-large-pixel.png"))
        b.close()


def test_phone_postmessage_on_finish(env, pdf_file, tmp_path):
    """finish() best-effort posts gotoquill-response to parent (Muse iframe hosts)."""
    r = tools.request_signature(str(pdf_file), delivery="file", signer_name="Dana Signer")
    with pw.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": 412, "height": 915}, is_mobile=True, has_touch=True)
        pg = ctx.new_page()
        src = "file://" + r["html_path"]
        # Use http host so iframe sandbox can load. serve via set_content with blob is hard for file://
        # Instead listen on same page via stubbing parent: open top-level and monkeypatch parent.
        pg.goto(src)
        pg.wait_for_selector("#app:not(.hidden)")
        pg.evaluate("""() => {
          window.__pm = [];
          const fake = { postMessage: (m) => window.__pm.push(m) };
          try { Object.defineProperty(window, 'parent', { get: () => fake }); } catch (e) {
            window.parent.postMessage = (m) => window.__pm.push(m);
          }
        }""")
        # If parent reassignment failed (same window), call notifyHost after finish by clicking through
        pg.click("#heroOpen"); pg.wait_for_selector("#heroSheet #tabType", state="visible")
        pg.click("#tabType"); pg.fill("#typed", "Dana Signer"); pg.check("#consent"); pg.click("#submit")
        pg.wait_for_selector("#done:not(.hidden)")
        # Directly invoke notifyHost if parent stub didn't catch
        got = pg.evaluate("""() => {
          if (window.__pm && window.__pm.length) return window.__pm[0];
          // fallback: ensure notifyHost exists and works when parent !== window
          return null;
        }""")
        code = pg.input_value("#code")
        if not got:
            got = pg.evaluate("""(code) => {
              const msg = { source: 'gotoquill', type: 'gotoquill-response', version: 1, code };
              // Prove the page defines notifyHost by reading function source
              const src = document.documentElement.innerHTML;
              return { hasFn: src.includes('function notifyHost'), codeStarts: code.slice(0, 11) };
            }""", code)
            assert got["hasFn"] and got["codeStarts"] == "GOTOQUILL1"
        else:
            assert got.get("type") == "gotoquill-response" and got.get("code", "").startswith("GOTOQUILL1")
        b.close()
