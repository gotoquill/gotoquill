"""Hero bottom-sheet must open on Android + iPhone viewports, top-level and sandboxed iframe.

Covers Chromium (Pixel Chrome/WebView stand-in) and WebKit (Safari / iOS WebView) when available.
"""
from __future__ import annotations

import functools
import http.server
import os
import shutil
import threading
from pathlib import Path

import pytest

from gotoquill import tools

pw = pytest.importorskip("playwright.sync_api")

CHROME = shutil.which("google-chrome") or "/usr/bin/google-chrome"
SHOTS = Path(os.environ["GOTOQUILL_SCREENSHOTS"]) if os.environ.get("GOTOQUILL_SCREENSHOTS") else None

DEVICES = {
    "pixel": dict(
        viewport={"width": 412, "height": 915},
        device_scale_factor=2.625,
        is_mobile=True,
        has_touch=True,
        user_agent=(
            "Mozilla/5.0 (Linux; Android 14; Pixel 9) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        ),
    ),
    "iphone": dict(
        viewport={"width": 390, "height": 844},
        device_scale_factor=3,
        is_mobile=True,
        has_touch=True,
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
        ),
    ),
}

SANDBOXES = {
    "top": None,
    "iframe-scripts": "allow-scripts",
    "iframe-scripts-sameorigin": "allow-scripts allow-same-origin",
}



def _tap(locator):
    """Real touch after iframe-aware visibility, stability and hit-target checks."""
    locator.tap(timeout=5000)


def _tap_sign_here(frame):
    # Chips use percentages of the page image. Before it loads, even a visible,
    # non-zero chip can be only ~2px tall and move after bounding_box() returns.
    frame.wait_for_function(
        """() => {
            const images = [...document.querySelectorAll('#pages .pg > canvas')];
            return images.length > 0 && images.every(im =>
                im.dataset.rendered === 'true' && im.width > 0 && im.height > 0);
        }""",
        timeout=5000,
    )
    _tap(frame.locator('#pages').get_by_role('button', name='Sign here', exact=True).first)


def _sandboxed_frame(page, src):
    page.set_content(
        '<!doctype html><meta name=viewport content="width=device-width,initial-scale=1">'
        '<style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>'
        f'<iframe id=f sandbox="allow-scripts" src="{src}"></iframe>'
    )
    frame = page.locator('iframe#f').element_handle().content_frame()
    frame.wait_for_selector('#app:not(.hidden)')
    return frame


def _watch_sheet_touch(frame):
    """Record only control geometry/input and dialog state, never signing data."""
    frame.evaluate(
        """() => {
            const sh = document.getElementById('heroSheet');
            const events = window.__heroTouchEvents = [];
            for (const type of ['pointerdown', 'pointerup', 'click', 'close', 'cancel']) {
                document.addEventListener(type, e => events.push({
                    type, target: e.target.tagName, id: e.target.id,
                    label: e.target.getAttribute('aria-label'),
                    pointerType: e.pointerType, trusted: e.isTrusted,
                    x: e.clientX, y: e.clientY,
                    rect: e.target.getBoundingClientRect().toJSON(),
                    open: sh.open,
                    imagesReady: [...document.querySelectorAll('#pages .pg > canvas')]
                        .every(im => im.dataset.rendered === 'true' && im.width > 0),
                }), true);
            }
            new MutationObserver(records => {
                for (const r of records) events.push({
                    type: 'open-change', wasOpen: r.oldValue !== null,
                    open: sh.open, rect: sh.getBoundingClientRect().toJSON(),
                });
            }).observe(sh, {attributes: true, attributeFilter: ['open'], attributeOldValue: true});
        }"""
    )


def _sheet_diagnostics(frame):
    return {
        'sheet': _sheet_metrics(frame),
        'events': frame.evaluate('window.__heroTouchEvents || []'),
        'buttons': frame.locator('#pages button.box').evaluate_all(
            """buttons => buttons.map(b => ({label: b.getAttribute('aria-label'),
                rect: b.getBoundingClientRect().toJSON()}))"""
        ),
    }


def _wait_for_sheet(frame):
    try:
        frame.wait_for_function(
            """() => {
                const sh = document.getElementById('heroSheet');
                if (!sh || !sh.open) return false;
                const r = sh.getBoundingClientRect(), cs = getComputedStyle(sh);
                return r.width > 0 && r.height > 80 && cs.display !== 'none'
                    && cs.visibility === 'visible' && Number(cs.opacity) > 0;
            }""",
            timeout=5000,
        )
    except pw.TimeoutError as exc:
        pytest.fail(f'{exc}\nHero sheet diagnostics: {_sheet_diagnostics(frame)}')


def _open_sheet_with_touch(frame):
    try:
        _tap_sign_here(frame)
    except pw.TimeoutError as exc:
        pytest.fail(f'{exc}\nSign-here diagnostics: {_sheet_diagnostics(frame)}')
    _wait_for_sheet(frame)
    events = frame.evaluate('window.__heroTouchEvents')
    assert any(e['type'] == 'pointerdown' and e['label'] == 'Sign here'
               and e['pointerType'] == 'touch' and e['trusted'] and e['imagesReady']
               for e in events), events
    m = _sheet_metrics(frame)
    assert m.get('dialogOpen') and m.get('visible') and m.get('h', 0) > 80, m
    assert m.get('padW', 0) > 40 and m.get('padH', 0) > 40, m


def _webkit_ok(p) -> bool:
    try:
        b = p.webkit.launch(headless=True)
        b.close()
        return True
    except Exception:
        return False


def _launch(p, engine: str):
    if engine == "chromium":
        kwargs = {"headless": True, "args": ["--no-sandbox"]}
        if os.path.exists(CHROME):
            kwargs["executable_path"] = CHROME
        return p.chromium.launch(**kwargs)
    return p.webkit.launch(headless=True)


def _sheet_metrics(frame):
    return frame.evaluate(
        """() => {
      const sh = document.getElementById('heroSheet');
      if (!sh) return {ok:false, why:'no-sheet', hero: document.body.classList.contains('hero')};
      const r = sh.getBoundingClientRect();
      const pad = document.getElementById('pad');
      const pr = pad ? pad.getBoundingClientRect() : null;
      return {
        ok: true,
        hero: document.body.classList.contains('hero'),
        sheetOpen: document.body.classList.contains('sheetOpen'),
        dialogOpen: !!sh.open,
        tag: sh.tagName,
        y: r.y, h: r.height, w: r.width,
        visible: !!(r.width && r.height) && getComputedStyle(sh).display !== 'none',
        padW: pr ? pr.width : 0,
        padH: pr ? pr.height : 0,
      };
    }"""
    )


@pytest.fixture
def served_html(env, pdf_file):
    r = tools.request_signature(str(pdf_file), delivery="file", signer_name="Dana Signer")
    html = Path(r["html_path"]).resolve()
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(html.parent))
    httpd = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/{html.name}"
    yield {"url": url, "file_url": html.as_uri(), "path": str(html)}
    httpd.shutdown()


@pytest.mark.parametrize("engine", ["chromium", "webkit"])
@pytest.mark.parametrize("device", ["pixel", "iphone"])
@pytest.mark.parametrize("embed", list(SANDBOXES))
def test_hero_sheet_opens(served_html, engine, device, embed):
    with pw.sync_playwright() as p:
        if engine == "webkit" and not _webkit_ok(p):
            pytest.skip("WebKit dependencies unavailable")
        browser = _launch(p, engine)
        ctx = browser.new_context(**DEVICES[device])
        page = ctx.new_page()
        errs = []
        page.on("pageerror", lambda e: errs.append(str(e)))

        sandbox = SANDBOXES[embed]
        src = served_html["url"]
        if sandbox is None:
            page.goto(src)
            page.wait_for_selector("#app:not(.hidden)")
            frame = page.main_frame
            _tap(page.locator("#heroOpen"))
        else:
            host = (
                "<!doctype html><meta name=viewport content=\"width=device-width,initial-scale=1\">"
                "<style>html,body{margin:0;height:100%}iframe{border:0;width:100%;height:100%}</style>"
                f'<iframe id=f sandbox="{sandbox}" src="{src}"></iframe>'
            )
            page.set_content(host)
            page.wait_for_selector("iframe#f")
            frame = page.frames[-1]
            frame.wait_for_selector("#app:not(.hidden)")
            _tap(page.frame_locator("iframe#f").locator("#heroOpen"))

        page.wait_for_timeout(400)
        m = _sheet_metrics(frame)
        assert m.get("hero") is True, m
        assert m.get("tag") == "DIALOG", m
        assert m.get("dialogOpen") is True, m
        assert m.get("visible") is True and m.get("h", 0) > 80, m
        assert m.get("padW", 0) > 40 and m.get("padH", 0) > 40, m
        # Mobile viewports: sheet near full height, pad at least ~40% of viewport
        if device in ("pixel", "iphone") and embed == "top":
            vh = page.viewport_size["height"]
            assert m.get("h", 0) >= vh * 0.75, m
            assert m.get("padH", 0) >= vh * 0.38, m  # pad large on phone

        # Close via dialog API (heroClose is IIFE-local), then reopen with Sign here chip
        frame.evaluate(
            """() => {
          const sh = document.getElementById('heroSheet');
          if (sh && sh.open) sh.close();
          document.body.classList.remove('sheetOpen');
        }"""
        )
        page.wait_for_timeout(100)
        _tap_sign_here(frame)
        page.wait_for_timeout(500)
        m2 = _sheet_metrics(frame)
        assert m2.get("dialogOpen") is True and m2.get("h", 0) > 80, m2

        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / f"hero-{engine}-{device}-{embed}.png"))

        assert not errs, errs
        browser.close()


def test_hero_sheet_file_url_top_level(served_html):
    """file:// top-level (how many chat apps hand the HTML to the user)."""
    with pw.sync_playwright() as p:
        browser = _launch(p, "chromium")
        ctx = browser.new_context(**DEVICES["pixel"])
        page = ctx.new_page()
        page.goto(served_html["file_url"])
        page.wait_for_selector("#app:not(.hidden)")
        _tap(page.locator("#heroOpen"))
        page.wait_for_timeout(400)
        m = _sheet_metrics(page.main_frame)
        assert m.get("dialogOpen") and m.get("h", 0) > 80, m
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / "hero-chromium-pixel-fileurl.png"))
        browser.close()



def test_hero_sheet_touch_signhere_sandboxed_iframe(served_html):
    """Real touch on Sign here inside sandbox=allow-scripts (Muse-style)."""
    with pw.sync_playwright() as p:
        browser = _launch(p, "chromium")
        ctx = browser.new_context(**DEVICES["pixel"])
        page = ctx.new_page()
        frame = _sandboxed_frame(page, served_html["url"])
        _watch_sheet_touch(frame)
        _open_sheet_with_touch(frame)
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / "hero-touch-signhere-iframe-pixel.png"))
        browser.close()


def test_hero_sheet_touch_signhere_delayed_render(served_html):
    """No clickable signature chip exists until its PDF canvas has finished rendering."""
    path = Path(served_html['path'])
    path.write_text(path.read_text().replace(
        "await page.render({", "await window.__renderGate; await page.render({"))
    with pw.sync_playwright() as p:
        browser = _launch(p, 'chromium')
        ctx = browser.new_context(**DEVICES['pixel'])
        ctx.add_init_script("window.__renderGate = new Promise(r => { window.__finishRender = r; });")
        page = ctx.new_page()
        frame = _sandboxed_frame(page, served_html['url'])
        frame.wait_for_selector('#pages canvas')
        assert frame.locator('#pages button.box').count() == 0
        _watch_sheet_touch(frame)
        frame.evaluate('() => { window.__finishRender(); }')
        _open_sheet_with_touch(frame)
        browser.close()


def test_hero_sheet_rescues_collapsed_modal(served_html):
    """Android WebView stand-in: showModal opens but sheet paints at 0 height / opacity 0 (backdrop only)."""
    with pw.sync_playwright() as p:
        browser = _launch(p, "chromium")
        ctx = browser.new_context(**DEVICES["pixel"])
        page = ctx.new_page()
        page.goto(served_html["url"])
        page.wait_for_selector("#app:not(.hidden)")
        page.evaluate(
            """() => {
          const sh = document.getElementById('heroSheet');
          const orig = sh.showModal.bind(sh);
          sh.showModal = function () {
            orig();
            // Simulate backdrop-only paint failure right after showModal.
            sh.style.height = '0px';
            sh.style.minHeight = '0px';
            sh.style.padding = '0px';
            sh.style.overflow = 'hidden';
            sh.style.opacity = '0';
          };
        }"""
        )
        _tap(page.locator("#heroOpen"))
        page.wait_for_timeout(600)
        m = _sheet_metrics(page.main_frame)
        assert m.get("visible") and m.get("h", 0) > 80, m
        assert m.get("padW", 0) > 40 and m.get("padH", 0) > 40, m
        # Either still modal or fell back to non-modal + #heroBack
        back = page.evaluate(
            """() => {
          const b = document.getElementById('heroBack');
          const sh = document.getElementById('heroSheet');
          return {
            backOn: !!(b && b.classList.contains('heroBackOn')),
            open: !!sh.open,
            opacity: getComputedStyle(sh).opacity,
            display: getComputedStyle(sh).display,
          };
        }"""
        )
        assert back["open"] and float(back["opacity"]) > 0.5 and back["display"] != "none", back
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / "hero-rescue-collapsed-pixel.png"))
        browser.close()


def test_hero_sheet_showmodal_throw_falls_back(served_html):
    """sandbox without allow-modals: showModal throws → open attribute + #heroBack."""
    with pw.sync_playwright() as p:
        browser = _launch(p, "chromium")
        ctx = browser.new_context(**DEVICES["pixel"])
        page = ctx.new_page()
        page.goto(served_html["url"])
        page.wait_for_selector("#app:not(.hidden)")
        page.evaluate(
            """() => {
          const sh = document.getElementById('heroSheet');
          sh.showModal = function () { throw new DOMException('sandbox', 'InvalidStateError'); };
        }"""
        )
        _tap_sign_here(page.main_frame)
        page.wait_for_timeout(500)
        m = _sheet_metrics(page.main_frame)
        assert m.get("visible") and m.get("h", 0) > 80, m
        back = page.evaluate(
            """() => ({
          backOn: document.getElementById('heroBack').classList.contains('heroBackOn'),
          openAttr: document.getElementById('heroSheet').hasAttribute('open'),
        })"""
        )
        assert back["backOn"] and back["openAttr"], back
        if SHOTS:
            SHOTS.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(SHOTS / "hero-showmodal-throw-fallback-pixel.png"))
        browser.close()
