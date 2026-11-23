"""End-to-end demo: a real stdio MCP client + headless Chrome signing, browser and MCP Apps (in-chat) paths.

    pip install -e .[dev] && python examples/e2e_demo.py /tmp/demo-out
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "gotoquill-demo").resolve()


def sc(res) -> dict:
    d = getattr(res, "structured_content", None) or getattr(res, "structuredContent", None) or json.loads(res.content[0].text)
    return d.get("result", d) if isinstance(d.get("result"), dict) else d


async def draw(page, frame=None):
    f = frame or page
    pad = f.locator("#pad")
    await pad.scroll_into_view_if_needed()
    b = await pad.bounding_box()
    x0, y0 = b["x"] + 30, b["y"] + b["height"] * 0.6
    await page.mouse.move(x0, y0)
    await page.mouse.down()
    for i in range(1, 60):
        await page.mouse.move(x0 + i * 6, y0 - 35 * ((i % 12) / 12 - 0.5) * (1 if (i // 12) % 2 else -1), steps=2)
    await page.mouse.up()
    await f.locator("#consent").check()


async def launch(p):
    kw = {"headless": True}
    if shutil.which("google-chrome"):
        kw["channel"] = "chrome"
    return await p.chromium.launch(**kw)


async def browser_path(pdf: Path) -> None:
    env = {**os.environ, "GOTOQUILL_OPEN_BROWSER": "0", "GOTOQUILL_DATA_DIR": str(OUT / ".data")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "gotoquill", "mcp"], env=env, cwd=str(ROOT))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        print("tools:", [t.name for t in (await s.list_tools()).tools])
        req = sc(await s.call_tool("request_signature", {"pdf_path": str(pdf), "signer_name": "Alex Example",
                                                         "add_date": True, "message": "Please sign the contract."}))
        print("request_signature ->", {k: req[k] for k in ("request_id", "sign_url", "output_path", "shown_in_chat")})
        async with async_playwright() as p:
            b = await launch(p)
            page = await b.new_page(viewport={"width": 1100, "height": 1400})
            await page.goto(req["sign_url"])
            await page.wait_for_selector("#pages img")
            await page.wait_for_timeout(500)
            await page.screenshot(path=str(OUT / "01-browser-sign-page.png"), full_page=True)
            await draw(page)
            await page.screenshot(path=str(OUT / "02-browser-signature-drawn.png"), full_page=True)
            await page.click("#submit")
            await page.wait_for_selector("#closed:not(.hidden)")
            await page.screenshot(path=str(OUT / "03-browser-signed.png"))
            await b.close()
        st = sc(await s.call_tool("get_signature_status", {"request_id": req["request_id"], "wait_seconds": 30}))
        print("get_signature_status ->", {k: st.get(k) for k in ("status", "output_path", "audit_path", "page_running")})
        assert st["status"] == "completed" and not st["page_running"]


HOST_HTML = """<!doctype html><html><body style="margin:0;font-family:sans-serif;background:#eee">
<div style="padding:10px 16px;background:#222;color:#fff">Demo MCP Apps host · assistant: "Please sign below"</div>
<iframe id="v" sandbox="allow-scripts allow-forms allow-modals" style="width:100%;height:1500px;border:0;background:#fff"></iframe>
<script>
const v = document.getElementById('v');
window.addEventListener('message', async e => { if (e.source !== v.contentWindow) return; const m = e.data;
  const reply = await window.hostBridge(JSON.stringify(m)); if (reply) v.contentWindow.postMessage(JSON.parse(reply), '*'); });
window.toView = m => v.contentWindow.postMessage(m, '*');
</script></body></html>"""


async def mcp_apps_path(pdf: Path) -> None:
    env = {**os.environ, "GOTOQUILL_OPEN_BROWSER": "0", "GOTOQUILL_DATA_DIR": str(OUT / ".data")}
    params = StdioServerParameters(command=sys.executable, args=["-m", "gotoquill", "mcp"], env=env, cwd=str(ROOT))
    ext = {"io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}}
    async with stdio_client(params) as (r, w), ClientSession(r, w, extensions=ext) as s:
        await s.initialize()
        tools = {t.name: t for t in (await s.list_tools()).tools}
        uri = (tools["request_signature"].meta or {})["ui"]["resourceUri"]
        res = (await s.read_resource(uri)).contents[0]
        print("ui resource:", uri, getattr(res, "mime_type", None), len(res.text), "chars")
        out = pdf.with_name("contract.in-chat.signed.pdf")
        args = {"pdf_path": str(pdf), "signer_name": "Alex Example", "output_path": str(out)}
        call = await s.call_tool("request_signature", args)
        req = sc(call)
        print("request_signature (MCP Apps client) ->", {k: req[k] for k in ("request_id", "shown_in_chat", "browser_opened")})
        initialized = asyncio.Event()

        async def bridge(raw: str):
            m = json.loads(raw)
            if m.get("method") == "ui/initialize":
                return json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": "2026-01-26",
                    "hostInfo": {"name": "demo-host", "version": "1"}, "hostCapabilities": {"serverTools": {}},
                    "hostContext": {"displayMode": "inline"}}})
            if m.get("method") == "ui/notifications/initialized":
                initialized.set()
                return None
            if m.get("method") == "tools/call":
                rr = await s.call_tool(m["params"]["name"], m["params"].get("arguments"))
                return json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": rr.model_dump(by_alias=True, exclude_none=True)})
            if "id" in m and m.get("method"):
                return json.dumps({"jsonrpc": "2.0", "id": m["id"], "result": {}})
            return None

        async with async_playwright() as p:
            b = await launch(p)
            page = await b.new_page(viewport={"width": 1000, "height": 1300})
            await page.expose_function("hostBridge", bridge)
            await page.set_content(HOST_HTML)
            await page.eval_on_selector("#v", "(el, html) => el.srcdoc = html", res.text)
            await asyncio.wait_for(initialized.wait(), 15)
            await page.evaluate("m => window.toView(m)", {"jsonrpc": "2.0", "method": "ui/notifications/tool-input",
                                                         "params": {"arguments": args}})
            await page.evaluate("m => window.toView(m)", {"jsonrpc": "2.0", "method": "ui/notifications/tool-result",
                                                         "params": call.model_dump(by_alias=True, exclude_none=True)})
            frame = page.frame_locator("#v")
            await frame.locator("#pages img").first.wait_for()
            await page.wait_for_timeout(500)
            await page.screenshot(path=str(OUT / "04-mcp-apps-in-chat-view.png"), full_page=True)
            await draw(page, frame)
            await page.screenshot(path=str(OUT / "05-mcp-apps-signature-drawn.png"), full_page=True)
            await frame.locator("#submit").click()
            await frame.locator("#closed:not(.hidden)").wait_for()
            await frame.locator("body").screenshot(path=str(OUT / "06-mcp-apps-signed.png"))
            await b.close()
        st = sc(await s.call_tool("get_signature_status", {"request_id": req["request_id"], "wait_seconds": 30}))
        print("get_signature_status ->", {k: st.get(k) for k in ("status", "output_path", "audit_path")})
        assert st["status"] == "completed"


async def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "examples"))
    from make_sample_pdf import make
    pdf = OUT / "contract.pdf"
    make(pdf)
    await browser_path(pdf)
    await mcp_apps_path(pdf)
    # render the signed PDFs for the record
    from gotoquill.pdfdoc import render_png
    for name, shot in (("contract.signed.pdf", "07-signed-pdf-browser.png"),
                       ("contract.in-chat.signed.pdf", "08-signed-pdf-in-chat.png")):
        (OUT / shot).write_bytes(render_png((OUT / name).read_bytes(), 0, 110 / 72))
    print("done:", sorted(x.name for x in OUT.iterdir()))


if __name__ == "__main__":
    asyncio.run(main())
