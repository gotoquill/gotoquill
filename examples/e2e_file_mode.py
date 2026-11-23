"""Real demo of no-connection (file) mode: make the HTML, sign it in headless Chrome at phone size
(file:// URL, no network), take the reply file, apply it, render the signed PDF.

    python examples/e2e_file_mode.py <pdf> <out_dir>
"""
import json
import sys
from pathlib import Path

from gotoquill.pdfdoc import render_png
from playwright.sync_api import sync_playwright

from gotoquill import offline

pdf, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
out.mkdir(parents=True, exist_ok=True)
r = offline.create_file_request(pdf_path=str(pdf), html_path=str(out / "Sample contract - sign.html"),
                                output_path=str(out / "Sample contract - signed.pdf"), signer_name="Alex Example",
                                message="Please sign the sample contract.", add_date=True)
print("request:", r["request_id"], r["html_path"], r["html_bytes"], "bytes")

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 393, "height": 852}, device_scale_factor=2.75, is_mobile=True, has_touch=True,
                        accept_downloads=True, user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36")
    requests = []
    ctx.on("request", lambda q: requests.append(q.url) if not q.url.startswith(("file:", "data:", "blob:")) else None)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(Path(r["html_path"]).as_uri())
    pg.screenshot(path=str(out / "file-mode-01-phone-open.png"))
    pg.locator("#signCard").scroll_into_view_if_needed()
    box = pg.locator("#pad").bounding_box()
    y0 = pg.evaluate("scrollY")
    # draw with touch-like pointer events
    pts = [(0.1 + 0.8 * i / 40, 0.5 + 0.25 * __import__("math").sin(i / 3)) for i in range(41)]
    pg.mouse.move(box["x"] + box["width"] * pts[0][0], box["y"] + box["height"] * pts[0][1])
    pg.mouse.down()
    for x, y in pts[1:]:
        pg.mouse.move(box["x"] + box["width"] * x, box["y"] + box["height"] * y, steps=2)
    pg.mouse.up()
    assert pg.evaluate("scrollY") == y0, "page scrolled while drawing"
    pg.check("#consent")
    pg.locator("#signCard").screenshot(path=str(out / "file-mode-02-phone-drawn.png"))
    pg.click("#submit")
    pg.wait_for_selector("#done:not(.hidden)")
    pg.screenshot(path=str(out / "file-mode-03-phone-reply-ready.png"))
    with pg.expect_download() as dl:
        pg.click("#download")
    resp_file = out / dl.value.suggested_filename
    dl.value.save_as(resp_file)
    code = pg.input_value("#code")
    b.close()
assert not errors, errors
assert not requests, f"network requests made: {requests}"
print("reply file:", resp_file.name, resp_file.stat().st_size, "bytes; code length", len(code))
(out / "Sample contract - signature code.txt").write_text(code)
res = offline.apply_signature_response(r["request_id"], response_path=str(resp_file))
print(json.dumps({k: v for k, v in res.items() if k != "audit"}, indent=2))
try:
    offline.apply_signature_response(r["request_id"], response_text=code)
except Exception as e:  # noqa: BLE001
    print("re-use blocked:", e)
(out / "file-mode-04-signed-pdf-last-page.png").write_bytes(render_png(Path(res["output_path"]).read_bytes(), -1, 110 / 72))
