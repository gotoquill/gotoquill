"""REAL end-to-end for the sealed FILE: the self-contained HTML opened from file:// (origin 'null') in phone-size
headless Chrome, against the REAL ntfy.sh relay.

    python examples/e2e_sealed_file.py /tmp/gotoquill-demo
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/gotoquill-demo")
out.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("GOTOQUILL_CONFIG_DIR", str(out / ".config"))
os.environ.setdefault("GOTOQUILL_DATA_DIR", str(out / ".data"))

from gotoquill import sealed  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

work = out / "sealed-file-work"
work.mkdir(exist_ok=True)
pdf = work / "contract.pdf"
pdf.write_bytes((ROOT / "examples" / "sample_contract.pdf").read_bytes())
r = sealed.create_sealed_request(pdf_path=str(pdf), signer_name="Dana Signer", add_date=True, as_file=True)
print("html:", r["html_path"])
with sync_playwright() as p:
    b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": 393, "height": 852}, device_scale_factor=2.75, is_mobile=True, has_touch=True)
    pg = ctx.new_page()
    errs, cons, origins = [], [], []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    pg.on("console", lambda m: cons.append(m.text))
    pg.on("request", lambda q: origins.append((q.method, q.url.split("?")[0][:60], q.headers.get("origin"))))
    pg.goto(Path(r["html_path"]).as_uri())
    pg.wait_for_selector("#app:not(.hidden), #closed:not(.hidden)", timeout=60000)
    print("origin:", pg.evaluate("location.origin"), "secureContext:", pg.evaluate("isSecureContext"))
    assert pg.is_visible("#app"), (pg.inner_text("#closed"), errs, cons)
    pg.screenshot(path=str(out / "sealed-file-01-open.png"))
    pg.click("#tabType"); pg.fill("#typed", "Dana Signer"); pg.check("#consent"); pg.click("#submit")
    pg.wait_for_selector("#done:not(.hidden)", timeout=60000)
    pg.screenshot(path=str(out / "sealed-file-02-signed.png"))
    print("requests:", json.dumps(origins, indent=1))
    b.close()
st = sealed.status(r["request_id"], wait_seconds=90)
print("status:", st["status"], st.get("output_path"))
assert st["status"] == "completed", st
print("OK")
