"""REAL end-to-end for sealed-link mode: web/ served on 127.0.0.1, REAL ntfy.sh relay, phone-size headless Chrome.

    python examples/e2e_sealed.py /tmp/gotoquill-demo
Writes sealed-*.png screenshots and checks that ntfy only ever held ciphertext.
"""
import functools
import http.server
import json
import os
import sys
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/gotoquill-demo")
out.mkdir(parents=True, exist_ok=True)

handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "web"))
httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
os.environ["GOTOQUILL_PAGE_URL"] = f"http://127.0.0.1:{httpd.server_address[1]}/"
os.environ.setdefault("GOTOQUILL_CONFIG_DIR", str(out / ".config"))
os.environ.setdefault("GOTOQUILL_DATA_DIR", str(out / ".data"))

from gotoquill import offline, relay, sealed  # noqa: E402

work = out / "sealed-work"
work.mkdir(exist_ok=True)
pdf = work / "contract.pdf"
pdf.write_bytes((ROOT / "examples" / "sample_contract.pdf").read_bytes())
r = sealed.create_sealed_request(pdf_path=str(pdf), signer_name="Dana Signer", add_date=True)
print("relay:", relay.get_relay().base_url, "| link:", r["sign_url"][:80] + "...")
(out / "sealed-00-qr.png").write_bytes(Path(r["qr_png_path"]).read_bytes())

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 393, "height": 852}, device_scale_factor=2.75, is_mobile=True, has_touch=True,
                        user_agent="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/126.0 Mobile Safari/537.36")
    pg = ctx.new_page()
    seen = []
    pg.on("request", lambda q: seen.append((q.method, q.url)))
    pg.goto(r["sign_url"])
    pg.wait_for_selector("#app:not(.hidden)", timeout=60000)
    assert "#" not in pg.url, "fragment should be removed from the address bar"
    pg.screenshot(path=str(out / "sealed-01-phone-open.png"))
    pg.locator("#signCard").scroll_into_view_if_needed()
    box = pg.locator("#pad").bounding_box()
    pts = [(.1, .6), (.2, .3), (.3, .7), (.4, .35), (.5, .65), (.6, .3), (.7, .7), (.85, .4)]
    pg.mouse.move(box["x"] + box["width"] * pts[0][0], box["y"] + box["height"] * pts[0][1]); pg.mouse.down()
    for x, y in pts[1:]:
        pg.mouse.move(box["x"] + box["width"] * x, box["y"] + box["height"] * y, steps=4)
    pg.mouse.up()
    pg.check("#consent")
    pg.screenshot(path=str(out / "sealed-02-phone-drawn.png"))
    pg.click("#submit")
    pg.wait_for_selector("#done:not(.hidden)", timeout=60000)
    pg.screenshot(path=str(out / "sealed-03-phone-signed.png"))
    hosts = sorted({u.split("/")[2] for _, u in seen})
    print("browser talked to:", hosts)

    st = sealed.status(r["request_id"], wait_seconds=90)
    print("status:", json.dumps(st))
    assert st["status"] == "completed", st
    audit = json.loads(Path(st["audit_path"]).read_text())
    assert audit["delivery"] == "sealed link via relay"
    from gotoquill.pdfdoc import render_png
    png = render_png(Path(st["output_path"]).read_bytes(), -1, 110 / 72)
    (out / "sealed-04-signed-pdf-last-page.png").write_bytes(png)
    pg2 = ctx.new_page()
    pg2.goto(r["sign_url"].split("#")[0] + "#" + r["sign_url"].split("#")[1])
    pg2.wait_for_selector("#closed:not(.hidden)", timeout=60000)
    pg2.screenshot(path=str(out / "sealed-05-link-reused.png"))
    b.close()

# What did ntfy.sh actually store? Pull both topics raw, straight from the relay.
d = offline._load(r["request_id"])
secret_markers = [b"%PDF", r["request_id"].encode(), b"Dana", b"iVBOR", b"gotoquill-response", b"consent",
                  d["original_sha256"].encode(), b"Sample", b"signature_png"]
report = {}
for kind in ("request_topic", "reply_topic"):
    t = d["sealed"][kind]
    raw = urllib.request.urlopen(urllib.request.Request(f"{relay.relay_url()}/{t}/json?poll=1&since=all",
                                 headers={"User-Agent": "gotoquill-e2e"})).read()
    msgs = [json.loads(x) for x in raw.splitlines() if x.strip()]
    items = []
    for m in msgs:
        att = m.get("attachment") or {}
        blob = urllib.request.urlopen(urllib.request.Request(att["url"], headers={"User-Agent": "gotoquill-e2e"})).read() if att.get("url") else m.get("message", "").encode()
        leaks = [s.decode() for s in secret_markers if s in blob or s in json.dumps(m).encode()]
        items.append({"event": m.get("event"), "message_text": m.get("message"), "attachment": {k: att.get(k) for k in ("name", "type", "size", "expires")},
                      "bytes": len(blob), "first16hex": blob[:16].hex(), "plaintext_markers_found": leaks})
        assert not leaks, leaks
    report[kind] = items
(out / "sealed-relay-inspection.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
print("OK: signed PDF", st["output_path"])
httpd.shutdown()
