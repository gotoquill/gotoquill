"""E2E for saved signatures: real stdio MCP server + headless Chrome, browser and MCP Apps paths.

    python examples/e2e_saved_signature.py /tmp/demo-out
1) browser: draw + tick "Save this signature" -> signed, saved
2) browser: page shows saved signature -> "Use saved signature" + consent + click -> signed (audit: reused)
3) MCP Apps in-chat: saved signature shown -> reuse; then delete from the page
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from playwright.async_api import async_playwright

sys.path.insert(0, str(Path(__file__).parent))
from e2e_demo import HOST_HTML, ROOT, draw, launch, sc  # noqa: E402

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "gotoquill-demo").resolve()
ENV = {**os.environ, "GOTOQUILL_OPEN_BROWSER": "0", "GOTOQUILL_DATA_DIR": str(OUT / ".data"),
       "GOTOQUILL_CONFIG_DIR": str(OUT / ".config")}


def shot(name: str) -> str:
    return str(OUT / name)


async def browser_round(s, pdf: Path, out: Path, reuse: bool, prefix: str):
    req = sc(await s.call_tool("request_signature", {"pdf_path": str(pdf), "output_path": str(out), "signer_name": "Alex Example"}))
    assert "iVBOR" not in json.dumps(req)
    async with async_playwright() as p:
        b = await launch(p)
        page = await b.new_page(viewport={"width": 1000, "height": 1300})
        await page.goto(req["sign_url"])
        await page.wait_for_selector("#pages img")
        await page.wait_for_timeout(400)
        if reuse:
            await page.wait_for_selector("#savedBox:not(.hidden)")
            await page.locator("#signCard").screenshot(path=shot(f"{prefix}-saved-signature-offered.png"))
            await page.screenshot(path=shot(f"{prefix}-saved-signature-page-full.png"), full_page=True)
            await page.click(".useSaved")
            assert await page.is_disabled("#submit")  # consent still required
            await page.check("#consent")
            await page.locator("#signCard").screenshot(path=shot(f"{prefix}-saved-signature-selected.png"))
        else:
            await draw(page)
            await page.check("#saveIt")
            await page.locator("#signCard").screenshot(path=shot(f"{prefix}-draw-and-save-checkbox.png"))
        await page.click("#submit")
        await page.wait_for_selector("#closed:not(.hidden)")
        await b.close()
    st = sc(await s.call_tool("get_signature_status", {"request_id": req["request_id"], "wait_seconds": 30}))
    assert st["status"] == "completed" and "iVBOR" not in json.dumps(st)
    a = json.loads(Path(st["audit_path"]).read_text())
    print(prefix, "audit:", {k: a[k] for k in ("method", "signature_source", "saved_for_next_time", "saved_signature_reused")})
    return a


async def mcp_apps_round(pdf: Path):
    params = StdioServerParameters(command=sys.executable, args=["-m", "gotoquill", "mcp"], env=ENV, cwd=str(ROOT))
    ext = {"io.modelcontextprotocol/ui": {"mimeTypes": ["text/html;profile=mcp-app"]}}
    async with stdio_client(params) as (r, w), ClientSession(r, w, extensions=ext) as s:
        await s.initialize()
        tools = {t.name: t for t in (await s.list_tools()).tools}
        res = (await s.read_resource(tools["request_signature"].meta["ui"]["resourceUri"])).contents[0]
        results = {}
        for rnd in ("reuse", "delete"):
            out = pdf.with_name(f"contract.in-chat-{rnd}.signed.pdf")
            args = {"pdf_path": str(pdf), "signer_name": "Alex Example", "output_path": str(out)}
            call = await s.call_tool("request_signature", args)
            req = sc(call)
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
                await page.evaluate("m => window.toView(m)", {"jsonrpc": "2.0", "method": "ui/notifications/tool-result",
                                                             "params": call.model_dump(by_alias=True, exclude_none=True)})
                f = page.frame_locator("#v")
                await f.locator("#pages img").first.wait_for()
                await f.locator("#savedBox:not(.hidden)").wait_for()
                await page.wait_for_timeout(400)
                # an agent calling the loader again gets no image / nonce
                again = sc(await s.call_tool("ui_load_document", {"sign_token": req["sign_token"]}))
                assert again["saved_signatures"] == [] and again["vault_nonce"] is None
                if rnd == "reuse":
                    await f.locator("#signCard").screenshot(path=shot("13-mcp-apps-saved-signature-offered.png"))
                    await f.locator(".useSaved").click()
                    await f.locator("#consent").check()
                    await f.locator("#signCard").screenshot(path=shot("14-mcp-apps-saved-signature-selected.png"))
                    await f.locator("#submit").click()
                    await f.locator("#closed:not(.hidden)").wait_for()
                else:
                    page.on("dialog", lambda d: asyncio.ensure_future(d.accept()))
                    await f.locator(".delSaved").click()
                    await f.locator("#savedBox").wait_for(state="hidden")
                    await f.locator("#signCard").screenshot(path=shot("15-mcp-apps-after-delete.png"))
                    await s.call_tool("cancel_request", {"request_id": req["request_id"]})
                await b.close()
            st = sc(await s.call_tool("get_signature_status", {"request_id": req["request_id"], "wait_seconds": 30}))
            results[rnd] = st
            if rnd == "reuse":
                assert st["status"] == "completed" and st["audit"]["signature_source"] == "saved signature reused"
                print("mcp-apps audit:", st["audit"]["signature_source"])
        assert not (OUT / ".config" / "signatures.json").exists()
        print("deleted from in-chat page: vault file gone")


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    import shutil
    shutil.rmtree(OUT / ".config", ignore_errors=True)
    from make_sample_pdf import make
    pdf = OUT / "contract.pdf"
    make(pdf)
    params = StdioServerParameters(command=sys.executable, args=["-m", "gotoquill", "mcp"], env=ENV, cwd=str(ROOT))
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        a1 = await browser_round(s, pdf, pdf.with_name("contract.saved-1.signed.pdf"), False, "10-browser")
        assert a1["saved_for_next_time"]
        raw = json.loads((OUT / ".config" / "signatures.json").read_text())
        print("vault encrypted:", raw["encrypted"], "mode:", oct((OUT / ".config" / "signatures.json").stat().st_mode & 0o777))
        a2 = await browser_round(s, pdf, pdf.with_name("contract.saved-2.signed.pdf"), True, "11-browser")
        assert a2["saved_signature_reused"]
    await mcp_apps_round(pdf)
    from gotoquill.pdfdoc import render_png
    Path(shot("12-signed-pdf-with-saved-signature.png")).write_bytes(render_png(pdf.with_name("contract.saved-2.signed.pdf").read_bytes(), 0, 110 / 72))
    print("ok")


if __name__ == "__main__":
    asyncio.run(main())
